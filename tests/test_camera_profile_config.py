"""Exercise catalogue refresh without importing Raspberry Pi/gphoto2 dependencies."""
import ast
from pathlib import Path
import unittest
from types import SimpleNamespace

source = Path(__file__).resolve().parents[1] / 'digie35' / 'digie35_server.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
names = {'_match_default_camera_profile', 'refresh_camera_config', 'apply_camera_profile'}
methods = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
namespace = {'CameraControlError': RuntimeError}
exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)


class CameraConfigTests(unittest.TestCase):
    def test_offline_defaults_do_not_use_the_previous_camera(self):
        profile = {'schema_version': 1, 'profile_version': 1, 'id': 'scan', 'label': 'Scan',
                   'parameters': {'iso': {'label': 'ISO', 'default': {'set': '100'},
                                          'mapping': {'default': {'id': 'iso'}}}}}
        camera = SimpleNamespace(_load_default_camera_profile=lambda: profile)
        result = namespace['_match_default_camera_profile'](camera, use_camera=False)
        self.assertIsNone(result['brand'])
        self.assertFalse(result['parameters'][0]['available'])
        self.assertEqual(result['parameters'][0]['default']['set'], '100')

    def test_refresh_reads_full_tree_before_catalogue_and_releases_session(self):
        calls = []
        camera = SimpleNamespace(
            _capture_in_progress=False,
            _acquire_capture_lock=lambda owner: calls.append('lock'),
            _release_capture_lock=lambda owner: calls.append('unlock'),
            _open_camera=lambda camera_id: calls.append(('open', camera_id)),
            _close_camera=lambda: calls.append('close'),
            _camera=SimpleNamespace(get_config=lambda: calls.append('full-tree')),
            _read_camera_config_catalog=lambda: calls.append('catalogue'),
            get_camera_config=lambda: {'parameters': ['fresh']},
        )
        result = namespace['refresh_camera_config'](camera, 'camera-a')
        self.assertEqual(result, {'parameters': ['fresh']})
        self.assertEqual(calls, ['lock', ('open', 'camera-a'), 'full-tree', 'catalogue', 'close', 'unlock'])


if __name__ == '__main__':
    unittest.main()
