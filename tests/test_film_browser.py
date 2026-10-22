"""Film deletion boundaries, companions and cached preview invalidation."""
import ast
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from digie35.mjpgserver import RingBuffer

source = Path(__file__).resolve().parents[1] / 'digie35/digie35_server.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in ('get_film', 'delete_captures')]
ns = {'os': os, 'CameraControlError': RuntimeError}
exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), ns)


class FilmBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'project/film'
        self.preview = self.root / '.previews/project/film'
        self.folder.mkdir(parents=True)
        self.preview.mkdir(parents=True)
        self.camera = SimpleNamespace(_cur_proj_dir=str(self.root), _media_dir=None,
            _capture_in_progress=False, _snapshot_list=RingBuffer(),
            _XMP_EXTENSION='.xmp', _LINK_EXTENSION='.lnk', _PREVIEW_SUFFIX='.preview.jpg', _PREVIEW_SUBDIR='.previews',
            _PREVIEW_SUFFIX_2='.preview.json', _MIN_PICTURE_FILE_SIZE=0,
            _check_film_exists=lambda *args: None,
            _get_path=lambda project, film, preview=False: str(self.preview if preview else self.folder),
            _get_descr=lambda *args: str(self.folder / '.description'))
        self.camera.get_film = lambda *args: ns['get_film'](self.camera, *args)

    def delete(self, names, **kwargs):
        return ns['delete_captures'](self.camera, kwargs.get('project', 'project'), 'film', names, kwargs.get('volume', True))

    def capture(self, name):
        (self.folder / name).write_bytes(b'raw')
        (self.preview / (name + '.preview.jpg')).write_bytes(b'jpeg')
        (self.preview / (name + '.preview.json')).write_text('{}')
        self.camera._snapshot_list.add('project/film/' + name, {'frame': b'jpeg'})

    def test_metadata_and_shared_xmp_and_cache(self):
        self.capture('frame.nef')
        self.capture('frame.jpg')
        (self.folder / 'frame.xmp').write_text('metadata')
        item = self.camera.get_film('project', 'film')['captured'][0]
        self.assertTrue(item['xmp'] and item['preview_json'] and item['preview'])
        self.assertGreater(item['modified'], 0)
        self.assertEqual(self.delete(['frame.nef'])['deleted'], ['frame.nef'])
        self.assertTrue((self.folder / 'frame.xmp').exists())
        self.assertIsNone(self.camera._snapshot_list.get('project/film/frame.nef'))
        self.assertFalse((self.preview / 'frame.nef.preview.json').exists())
        self.assertEqual(self.delete(['frame.jpg'])['deleted'], ['frame.jpg'])
        self.assertFalse((self.folder / 'frame.xmp').exists())

    def test_camera_record_only_and_invalid_requests(self):
        (self.folder / 'remote.nef.lnk').write_text('/camera/DCIM/remote.nef')
        (self.folder / 'remote.xmp').write_text('metadata')
        (self.preview / 'remote.nef.preview.jpg').write_bytes(b'jpeg')
        (self.preview / 'remote.nef.preview.json').write_text('{}')
        self.camera._snapshot_list.add('project/film/remote.nef', {'frame': b'jpeg'})
        self.assertTrue(self.camera.get_film('project', 'film')['captured'][0]['camera_only'])
        for names in (['../remote.nef'], ['missing.nef'], ['remote.nef', '../bad']):
            self.assertIn('error', self.delete(names))
        self.assertIn('error', self.delete(['remote.nef'], project='..'))
        self.assertIn('error', self.delete(['remote.nef'], volume='changed'))
        self.camera._capture_in_progress = True
        self.assertIn('error', self.delete(['remote.nef']))
        self.camera._capture_in_progress = False
        self.assertEqual(self.delete(['remote.nef'])['deleted'], ['remote.nef'])
        self.assertFalse((self.folder / 'remote.nef.lnk').exists())
        self.assertFalse((self.folder / 'remote.xmp').exists())
        self.assertFalse((self.preview / 'remote.nef.preview.jpg').exists())
        self.assertFalse((self.preview / 'remote.nef.preview.json').exists())
        self.assertIsNone(self.camera._snapshot_list.get('project/film/remote.nef'))

    def test_partial_failure_is_reported_and_other_image_deleted(self):
        self.capture('bad.nef')
        self.capture('good.nef')
        (self.folder / 'bad.xmp').mkdir()
        result = self.delete(['bad.nef', 'good.nef'])
        self.assertIn('bad.nef', result['errors'])
        self.assertEqual(result['deleted'], ['good.nef'])
        self.assertTrue((self.folder / 'bad.nef').exists())

    def test_ring_removal_preserves_order_after_wrap(self):
        ring = RingBuffer(3)
        for i in range(5):
            ring.add(str(i), i)
        ring.remove('3')
        self.assertEqual(ring.get(0), 4)
        self.assertEqual(ring.get(1), 2)
        ring.add('5', 5)
        self.assertEqual(ring.foreach(lambda key, value: value), [5, 4, 2])


if __name__ == '__main__':
    unittest.main()
