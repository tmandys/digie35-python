"""Tests for disk-backed user camera profiles."""

import tempfile
import unittest

from digie35.camera_profiles import CameraProfiles


class CameraProfileStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.profiles = CameraProfiles(self.temporary_directory.name)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_save_list_update_and_delete(self):
        saved = self.profiles.save({
            "schema_version": 1,
            "name": "Sony negativy",
            "parameters": {"/main/imgsettings/iso": {"default": {"check": "100"}}},
        })
        profile = saved["profiles"][0]
        self.assertRegex(profile["id"], r"^[a-f0-9]{32}$")
        self.assertEqual(profile["name"], "Sony negativy")
        self.assertEqual(saved["saved_profile"]["id"], profile["id"])

        updated = self.profiles.save({
            "schema_version": 1,
            "id": profile["id"],
            "name": "Sony negativy upraveno",
            "parameters": {},
        })
        self.assertEqual(len(updated["profiles"]), 1)
        self.assertEqual(updated["profiles"][0]["id"], profile["id"])
        self.assertEqual(updated["profiles"][0]["name"], "Sony negativy upraveno")
        self.assertEqual(updated["saved_profile"]["id"], profile["id"])

        self.assertEqual(self.profiles.delete(profile["id"]), {"profiles": []})

    def test_rejects_a_path_instead_of_a_uuid(self):
        with self.assertRaises(ValueError):
            self.profiles.delete("../../profile")
