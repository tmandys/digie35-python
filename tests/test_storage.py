"""Run: python -m unittest discover -s tests -p test_storage.py"""
import argparse
import ast
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from digie35.storage import LocalStorage, default_storage_directory


class StorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_default_and_xdg_override(self):
        for value in ("", "relative/path"):
            with patch.dict(os.environ, {"XDG_DATA_HOME": value}):
                self.assertEqual(Path(default_storage_directory()), Path.home() / ".local/share/digie35")
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root)}):
            self.assertEqual(Path(default_storage_directory()), self.root / "digie35")

    def test_directory_expansion_and_creation(self):
        with patch.dict(os.environ, {"DIGIE35_TEST_STORAGE": str(self.root)}):
            storage = LocalStorage("$DIGIE35_TEST_STORAGE/data")
        self.assertEqual(storage.directory, (self.root / "data").resolve())
        self.assertTrue(storage.directory.is_dir())
        self.assertEqual(list(storage.directory.iterdir()), [])
        with patch.dict(os.environ, {"HOME": str(self.root), "USERPROFILE": str(self.root)}):
            self.assertEqual(LocalStorage("~/profiles").directory, (self.root / "profiles").resolve())

    def test_round_trip_and_reopen(self):
        storage = LocalStorage(self.root)
        self.assertEqual(storage.list("wb_profiles"), [])
        profile = {"name": "Oranžová maska", "matrix": [[0.25, 1.5, 0.0]]}
        storage.save("wb_profiles", "film_1", profile)
        reopened = LocalStorage(self.root)
        self.assertEqual(reopened.load("wb_profiles", "film_1"), profile)
        self.assertEqual(reopened.list("wb_profiles"), ["film_1"])
        (self.root / "wb_profiles/.tmp-in-progress.json").write_text("partial")
        self.assertEqual(reopened.list("wb_profiles"), ["film_1"])

    def test_failed_save_preserves_previous_profile_and_removes_temporary_file(self):
        storage = LocalStorage(self.root)
        storage.save("wb_profiles", "film", {"version": 1})
        with patch("digie35.storage.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                storage.save("wb_profiles", "film", {"version": 2})
        self.assertEqual(storage.load("wb_profiles", "film"), {"version": 1})
        self.assertEqual([p.name for p in (self.root / "wb_profiles").iterdir()], ["film.json"])
        with self.assertRaises(ValueError):
            storage.save("wb_profiles", "film", {"gain": float("nan")})
        self.assertEqual(storage.load("wb_profiles", "film"), {"version": 1})
        storage.save("wb_profiles", "film", {"version": 3})
        self.assertEqual(storage.load("wb_profiles", "film"), {"version": 3})

    def test_invalid_paths_missing_and_corrupt_records(self):
        storage = LocalStorage(self.root)
        for value in ("", "..", "../outside", "a/b", "a\\b", str(self.root)):
            with self.assertRaises(ValueError):
                storage.save("wb_profiles", value, {})
            with self.assertRaises(ValueError):
                storage.list(value)
        with self.assertRaises(FileNotFoundError):
            storage.load("wb_profiles", "missing")
        (self.root / "wb_profiles").mkdir()
        (self.root / "wb_profiles/broken.json").write_text("{broken")
        with self.assertRaises(json.JSONDecodeError):
            storage.load("wb_profiles", "broken")
        with self.assertRaises(OSError):
            LocalStorage(self.root / "wb_profiles/broken.json")
        with self.assertRaises(ValueError):
            LocalStorage("")

    def test_startup_detects_write_failure(self):
        with patch("digie35.storage.tempfile.TemporaryFile", side_effect=PermissionError("read only")):
            with self.assertRaises(PermissionError):
                LocalStorage(self.root)

    def test_server_argument_without_importing_camera_dependencies(self):
        source = Path(__file__).resolve().parents[1] / "digie35/digie35_server.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                 and any(isinstance(arg, ast.Constant) and arg.value == "--storage-directory" for arg in node.args)]
        self.assertEqual(len(calls), 1)
        parser = argparse.ArgumentParser()
        exec(compile(ast.Expression(calls[0]), str(source), "eval"),
             {"argParser": parser, "default_storage_directory": default_storage_directory})
        self.assertEqual(parser.parse_args([]).storage_dir, default_storage_directory())
        self.assertEqual(parser.parse_args(["--storage-directory", str(self.root)]).storage_dir, str(self.root))


if __name__ == "__main__":
    unittest.main()
