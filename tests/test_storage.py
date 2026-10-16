"""Tests for shared local JSON storage."""

import tempfile
import unittest

from digie35.storage import LocalStorage


class LocalStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_save_load_and_list(self):
        self.storage.save("camera_profiles", "a1", {"name": "Test"})
        self.assertEqual(self.storage.list("camera_profiles"), ["a1"])
        self.assertEqual(self.storage.load("camera_profiles", "a1"), {"name": "Test"})

    def test_rejects_path_components(self):
        with self.assertRaises(ValueError):
            self.storage.save("camera_profiles", "../../unsafe", {})
