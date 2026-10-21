"""Archived analysis persistence without camera/OpenCV dependencies."""
import ast
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

source = Path(__file__).resolve().parents[1] / 'digie35/digie35_server.py'
method = next(node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
              if isinstance(node, ast.FunctionDef) and node.name == 'analyze_archived_preview')
ns = {'json': json, 'os': os, 'CameraControlError': RuntimeError}
exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), ns)


class ArchivedAnalysisTests(unittest.TestCase):
    def test_saved_source_is_analyzed_and_metadata_and_cache_are_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'project/film'
            folder.mkdir(parents=True)
            image = folder / 'frame.preview.jpg'
            info = folder / 'frame.preview.json'
            image.write_bytes(b'original-jpeg')
            info.write_text(json.dumps({'rotation': 90, 'negative': True, 'custom': 42}))
            calls = []
            def analyzer(frame):
                calls.append(frame)
                return SimpleNamespace(analyze=lambda: calls.append('analyze'), get_result=lambda: {'score': 123})
            ns['digie35image'] = SimpleNamespace(ImageAnalysis=analyzer, NumpyEncoder=json.JSONEncoder)
            cached = {'json': {}, 'frame': b'original-jpeg'}
            camera = SimpleNamespace(_get_path=lambda *args, **kwargs: root,
                _snapshot_list=SimpleNamespace(get=lambda name: cached))
            result = ns['analyze_archived_preview'](camera, 'project/film/frame')
            self.assertEqual(calls, [b'original-jpeg', 'analyze'])
            self.assertEqual(result['vision'], {'score': 123})
            metadata = json.loads(info.read_text())
            self.assertEqual(metadata, {'rotation': 90, 'negative': True, 'custom': 42, 'vision': {'score': 123}})
            self.assertEqual(cached['json'], metadata)
            self.assertEqual(image.read_bytes(), b'original-jpeg')
            before = info.read_bytes()
            for name in ('../film/frame', '/film/frame', 'project/../frame', 'project\\film/frame', 'project/film/missing'):
                with self.assertRaises(RuntimeError):
                    ns['analyze_archived_preview'](camera, name)
            self.assertEqual(info.read_bytes(), before)
            ns['digie35image'].ImageAnalysis = lambda frame: (_ for _ in ()).throw(ValueError('decode failed'))
            with self.assertRaises(ValueError):
                ns['analyze_archived_preview'](camera, 'project/film/frame')
            self.assertEqual(info.read_bytes(), before)
