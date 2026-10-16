"""Tests for built-in camera-profile data."""

from pathlib import Path
import unittest

import yaml


PROFILE_PATH = Path(__file__).resolve().parents[1] / "digie35" / "camera_profiles" / "default-scan.yaml"


class CameraProfileTests(unittest.TestCase):
    def test_default_scan_profile_has_the_primary_safety_checks(self):
        with PROFILE_PATH.open(encoding="utf-8") as profile_file:
            profile = yaml.safe_load(profile_file)

        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["id"], "default-scan")

        parameters = profile["parameters"]
        self.assertEqual(parameters["exposure_mode"]["default"]["check"], "Av")
        self.assertEqual(parameters["aperture"]["default"]["check"], "f/8")
        self.assertEqual(parameters["aperture"]["overrides"]["focusing"]["set"], "f/2.8")
        self.assertEqual(parameters["iso"]["default"]["check"], "100")
        self.assertTrue(parameters["aeb"]["default"]["blocking"])

