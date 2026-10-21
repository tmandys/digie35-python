"""Tests for built-in camera-profile data."""

from pathlib import Path
import unittest

import yaml


PROFILE_PATH = Path(__file__).resolve().parents[1] / "digie35" / "camera_profiles" / "parameters.yaml"


class CameraProfileTests(unittest.TestCase):
    def test_default_scan_template_has_independent_values_and_flags(self):
        with PROFILE_PATH.open(encoding="utf-8") as profile_file:
            profile = yaml.safe_load(profile_file)
        self.assertEqual(profile["profile_version"], 2)
        parameters = profile["parameters"]
        aperture = parameters["aperture"]
        self.assertEqual(aperture["default"], {"display": True, "value": "f/8", "set": False, "check": False})
        for mode in ("mf", "af"):
            self.assertEqual(aperture["overrides"][mode], {"value": "f/8", "set": True, "check": True})
        self.assertEqual(aperture["overrides"]["focus"], {"value": "f/2.8", "set": True, "check": False})
        self.assertEqual(parameters["exposure_mode"]["overrides"]["calibration"], {"value": "M", "set": True, "check": True})
        self.assertFalse(parameters["exposure_compensation"]["default"]["set"])
        self.assertTrue(parameters["iso"]["default"]["check"])
        for name in ("white_balance_adjust_ab", "white_balance_adjust_gm"):
            self.assertEqual(parameters[name]["overrides"]["calibration"], {"value": "0", "set": False, "check": False})
        self.assertNotIn("default", parameters["aeb"])
        self.assertIn("mapping", parameters["aeb"])
        self.assertEqual(parameters["white_balance"]["mapping"]["sony"]["values"]["color_temperature"], "Choose Color Temperature")
