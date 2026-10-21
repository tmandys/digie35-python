"""Broken entry actions remain editable but cannot be saved or executed."""
import ast
from pathlib import Path
import tempfile
import unittest

# Storage tests do not need PyYAML or built-in mapping files.
path = Path(__file__).resolve().parents[1] / 'digie35' / 'camera_mappings.py'
tree = ast.parse(path.read_text(encoding='utf-8'))
tree.body = [node for node in tree.body if not (isinstance(node, ast.Import) and any(alias.name == 'yaml' for alias in node.names))]
ns = {'__file__': str(path)}
exec(compile(tree, str(path), 'exec'), ns)
CameraMappings = ns['CameraMappings']
CameraMappings._builtins = staticmethod(lambda: [])


class MappingRepairTests(unittest.TestCase):
    def test_broken_file_is_listed_and_can_be_repaired(self):
        with tempfile.TemporaryDirectory() as directory:
            mappings = CameraMappings(directory)
            original = {'schema_version': 1, 'name': 'Repair', 'actions': {
                'enter_mf': {'steps': [{'apply_profile': True}]}}}
            saved = mappings.save(original)['saved_mapping']
            for steps in ([], [{'apply_profile': True}, {'apply_profile': True}]):
                saved['actions']['enter_mf']['steps'] = steps
                mappings.storage.save(mappings.CATEGORY, saved['id'], saved)
                self.assertEqual(len(mappings.list()['mappings']), 1)
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    mappings.get(saved['id'])
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    mappings.save(saved)
            saved['actions']['enter_mf']['steps'] = [{'apply_profile': True}]
            mappings.save(saved)
            self.assertEqual(mappings.get(saved['id'])['actions']['enter_mf']['steps'], [{'apply_profile': True}])


if __name__ == '__main__': unittest.main()
