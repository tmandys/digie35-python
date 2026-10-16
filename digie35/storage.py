"""Local server data, separate from removable photo/project storage."""

import json
import os
from pathlib import Path
import re
import tempfile


def default_storage_directory():
    base = os.environ.get("XDG_DATA_HOME", "")
    if not os.path.isabs(base):
        base = os.path.expanduser("~/.local/share")
    return os.path.join(base, "digie35")


class LocalStorage:
    """JSON records grouped by category.

    Categories and record names are identifiers, never paths. Concurrent
    writes replace an entire record atomically, so readers see either the old
    or the new JSON document.
    """

    def __init__(self, directory):
        if not os.fspath(directory).strip():
            raise ValueError("Storage directory must not be empty")
        self.directory = Path(os.path.expandvars(os.path.expanduser(directory))).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=self.directory):
            pass

    def _path(self, category, name=None):
        for value in (category,) if name is None else (category, name):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
                raise ValueError("Storage identifiers must contain only letters, digits, '_' or '-'")
        directory = self.directory / category
        path = directory if name is None else directory / (name + ".json")
        if not path.resolve().is_relative_to(self.directory):
            raise ValueError("Storage path leaves the configured directory")
        return path

    def list(self, category):
        directory = self._path(category)
        if not directory.exists():
            return []
        return sorted(path.stem for path in directory.glob("*.json")
                      if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", path.stem)
                      and path.is_file() and not path.is_symlink())

    def load(self, category, name):
        with self._path(category, name).open(encoding="utf-8") as stream:
            return json.load(stream)

    def save(self, category, name, data):
        path = self._path(category, name)
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                             prefix=".tmp-", suffix=".json", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
