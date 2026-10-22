"""Local film transfers with collision checks and rollback on filesystem errors."""
import errno
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile


def move_film_files(root, project, film, target_project, target_film, names, captures):
    root = Path(root).resolve()
    for part in (project, film, target_project, target_film):
        if not isinstance(part, str) or not part or part in ('.', '..') or any(c in part for c in '/\\:'):
            raise ValueError('Invalid film path')
    if (project, film) == (target_project, target_film):
        raise ValueError('Choose a different film')
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or n not in captures or any(c in n for c in '/\\:') for n in names):
        raise ValueError('Invalid image selection; refresh the film')
    names = list(dict.fromkeys(names))
    source, target = root / project / film, root / target_project / target_film
    source_preview = root / '.previews' / project / film
    target_preview = root / '.previews' / target_project / target_film

    def check(path):
        for part in (path, *path.parents):
            if part == root:
                break
            if part.is_symlink():
                raise ValueError(f'Symbolic links are not supported: {path.name}')
        if not path.resolve().is_relative_to(root):
            raise ValueError('Invalid file path')

    for folder in (source, target, source_preview, target_preview):
        check(folder)
    if not source.is_dir() or not target.is_dir():
        raise ValueError('Source or destination film no longer exists')

    # (source file or None, destination file, remove source, replacement JSON)
    plan = []
    for name in names:
        for suffix in ('', '.lnk'):
            dest = target / (name + suffix)
            check(dest)
            if dest.exists():
                raise ValueError(f'Destination already contains {name} or its placeholder; nothing moved')
        primary = [source / (name + suffix) for suffix in ('', '.lnk') if (source / (name + suffix)).exists()]
        if not primary:
            raise ValueError(f'Source no longer exists: {name}')
        for path in primary:
            plan.append((path, target / path.name, True, None))
        for suffix in ('.preview.jpg', '.preview.json'):
            path, dest = source_preview / (name + suffix), target_preview / (name + suffix)
            check(path)
            metadata = None
            if path.is_file() and suffix.endswith('.json'):
                metadata = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(metadata, dict):
                    raise ValueError(f'Invalid preview JSON: {name}')
                metadata['image_name'] = f'{target_project}/{target_film}/{name}'
            plan.append((path if path.exists() else None, dest, True, metadata))

    for stem in dict.fromkeys(Path(name).stem for name in names):
        path, dest = source / (stem + '.xmp'), target / (stem + '.xmp')
        check(path)
        # Do not change an XMP shared by an unrelated destination RAW/JPEG.
        if any(p.stem == stem or (p.suffix == '.lnk' and Path(p.stem).stem == stem)
               for p in target.iterdir() if p.suffix.lower() != '.xmp' and not p.name.startswith('.')):
            raise ValueError(f'Destination contains another image sharing {stem}.xmp; nothing moved')
        keep_source = any(Path(name).stem == stem and name not in names for name in captures)
        plan.append((path if path.exists() else None, dest, not keep_source, None))

    for src, dest, _, _ in plan:
        check(dest)
        if dest.exists() and not dest.is_file():
            raise ValueError(f'Expected a regular file: {dest.name}')
        if src:
            check(src)
            if not src.is_file():
                raise ValueError(f'Expected a regular file: {src.name}')

    staging = Path(tempfile.mkdtemp(prefix='.film-move-', dir=source))
    backups, installed = [], []
    try:
        target_preview.mkdir(parents=True, exist_ok=True)
        for src, dest, remove, metadata in plan:
            # Only companions may replace destination files. Primary names were
            # preflighted above and are created exclusively again below.
            primary = dest.parent == target and dest.suffix.lower() != '.xmp'
            if not primary and dest.exists():
                backup = staging / str(len(backups))
                os.replace(dest, backup)
                backups.append((backup, dest))
            if src:
                if metadata is not None:
                    with dest.open('x', encoding='utf-8') as output:
                        installed.append(dest)
                        json.dump(metadata, output, ensure_ascii=False, indent=2)
                else:
                    try:
                        if not remove:
                            raise OSError(errno.ENOTSUP, 'Shared XMP needs an independent copy')
                        os.link(src, dest)
                        installed.append(dest)
                    except OSError as error:
                        if error.errno == errno.EEXIST:
                            raise
                        # FAT/exFAT storage may not support hard links.
                        with dest.open('xb') as output:
                            installed.append(dest)
                            with src.open('rb') as original:
                                shutil.copyfileobj(original, output)
                        shutil.copystat(src, dest)
        # Sources remain intact until every destination file has been prepared.
        for src, _, remove, _ in plan:
            if src and remove:
                backup = staging / str(len(backups))
                os.replace(src, backup)
                backups.append((backup, src))
    except Exception:
        # If rollback itself fails, keep staging for recovery rather than deleting it.
        for dest in reversed(installed):
            dest.unlink(missing_ok=True)
        for backup, original in reversed(backups):
            os.replace(backup, original)
        shutil.rmtree(staging)
        raise
    try:
        shutil.rmtree(staging)
    except OSError:
        logging.getLogger(__name__).exception('Move completed but backup cleanup failed: %s', staging)
    return names
