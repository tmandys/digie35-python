"""Local moves: collisions, orphaned companions, camera records and rollback."""
import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from digie35.film_files import move_film_files


class FilmMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'p/f'
        self.dst = self.root / 'q/g'
        self.sp = self.root / '.previews/p/f'
        self.dp = self.root / '.previews/q/g'
        for folder in (self.src, self.dst, self.sp, self.dp):
            folder.mkdir(parents=True)
        self.captures = {}

    def photo(self, name='a.nef', link=False):
        (self.src / (name + ('.lnk' if link else ''))).write_bytes(b'original')
        self.captures[name] = {'name': name}

    def move(self, names=None):
        return move_film_files(self.root, 'p', 'f', 'q', 'g', names or list(self.captures), self.captures)

    def test_move_link_with_companions_replaces_orphans(self):
        self.photo(link=True)
        for folder in (self.sp, self.dp):
            (folder / 'a.nef.preview.jpg').write_bytes(b'new' if folder == self.sp else b'old')
            (folder / 'a.nef.preview.json').write_text(json.dumps({'image_name': 'p/f/a.nef', 'rotation': 90}))
        (self.src / 'a.xmp').write_bytes(b'new xmp')
        (self.dst / 'a.xmp').write_bytes(b'old xmp')
        self.assertEqual(self.move(), ['a.nef'])
        self.assertFalse((self.src / 'a.nef.lnk').exists())
        self.assertEqual((self.dst / 'a.nef.lnk').read_bytes(), b'original')
        self.assertEqual((self.dst / 'a.xmp').read_bytes(), b'new xmp')
        self.assertEqual((self.dp / 'a.nef.preview.jpg').read_bytes(), b'new')
        self.assertEqual(json.loads((self.dp / 'a.nef.preview.json').read_text()), {'image_name': 'q/g/a.nef', 'rotation': 90})
        self.assertEqual(list(self.src.iterdir()), [])
        self.assertEqual(list(self.sp.iterdir()), [])

    def test_missing_source_companions_remove_target_orphans(self):
        self.photo()
        for path in (self.dp / 'a.nef.preview.jpg', self.dp / 'a.nef.preview.json', self.dst / 'a.xmp'):
            path.write_bytes(b'orphan')
        self.move()
        self.assertEqual(list(self.dp.iterdir()), [])
        self.assertFalse((self.dst / 'a.xmp').exists())

    def test_raw_or_link_collision_blocks_entire_selection(self):
        self.photo('a.nef')
        self.photo('b.nef')
        for suffix in ('', '.lnk'):
            conflict = self.dst / ('b.nef' + suffix)
            conflict.write_bytes(b'destination')
            with self.assertRaisesRegex(ValueError, 'already contains'):
                self.move()
            self.assertTrue((self.src / 'a.nef').exists())
            self.assertFalse((self.dst / 'a.nef').exists())
            self.assertEqual(conflict.read_bytes(), b'destination')
            conflict.unlink()

    def test_shared_source_xmp_is_copied_independently(self):
        self.photo('a.nef')
        self.photo('a.jpg')
        (self.src / 'a.xmp').write_text('original')
        self.move(['a.nef'])
        (self.dst / 'a.xmp').write_text('changed')
        self.assertEqual((self.src / 'a.xmp').read_text(), 'original')
        self.assertTrue((self.src / 'a.jpg').exists())

    def test_shared_destination_xmp_blocks_move(self):
        self.photo()
        (self.dst / 'a.jpg.lnk').write_text('other capture')
        with self.assertRaisesRegex(ValueError, 'sharing'):
            self.move()
        self.assertTrue((self.src / 'a.nef').exists())

    def test_exfat_copy_fallback(self):
        self.photo()
        with patch('digie35.film_files.os.link', side_effect=OSError(errno.ENOTSUP, 'unsupported')):
            self.move()
        self.assertEqual((self.dst / 'a.nef').read_bytes(), b'original')
        self.assertFalse((self.src / 'a.nef').exists())

    def test_failure_restores_originals_and_destination_orphans(self):
        self.photo()
        (self.sp / 'a.nef.preview.jpg').write_bytes(b'preview')
        (self.dp / 'a.nef.preview.jpg').write_bytes(b'orphan')
        import os
        replace = os.replace
        def fail_at_source_removal(src, dst):
            if Path(src) == self.sp / 'a.nef.preview.jpg':
                raise PermissionError('simulated')
            return replace(src, dst)
        with patch('digie35.film_files.os.replace', side_effect=fail_at_source_removal):
            with self.assertRaisesRegex(PermissionError, 'simulated'):
                self.move()
        self.assertEqual((self.src / 'a.nef').read_bytes(), b'original')
        self.assertEqual((self.dp / 'a.nef.preview.jpg').read_bytes(), b'orphan')
        self.assertEqual((self.sp / 'a.nef.preview.jpg').read_bytes(), b'preview')
        self.assertFalse((self.dst / 'a.nef').exists())

    def test_invalid_selection_and_same_film(self):
        self.photo()
        with self.assertRaises(ValueError):
            self.move(['../a.nef'])
        with self.assertRaises(ValueError):
            move_film_files(self.root, 'p', 'f', 'p', 'f', ['a.nef'], self.captures)
        self.assertTrue((self.src / 'a.nef').exists())


if __name__ == '__main__':
    unittest.main()
