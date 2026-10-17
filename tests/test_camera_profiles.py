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
        self.assertEqual(parameters["aperture"]["overrides"]["focus"]["set"], "f/2.8")
        self.assertEqual(parameters["iso"]["default"]["check"], "100")
        self.assertEqual(parameters["focus_mode"]["overrides"]["af"]["set"], "autofocus")
        self.assertEqual(parameters["focus_mode"]["overrides"]["mf"]["set"], "manual_focus")
        self.assertTrue(parameters["aeb"]["default"]["blocking"])
        self.assertEqual(parameters["exposure_mode"]["overrides"]["calibration"]["set"], "M")
        self.assertEqual(parameters["white_balance"]["overrides"]["calibration"]["set"], "color_temperature")
        self.assertEqual(parameters["white_balance"]["mapping"]["canon"]["values"]["color_temperature"], "Color Temperature")
        self.assertEqual(parameters["white_balance"]["mapping"]["sony"]["values"]["color_temperature"], "Choose Color Temperature")
        self.assertEqual(parameters["white_balance"]["mapping"]["nikon"]["values"]["color_temperature"], "Color Temperature")
        self.assertEqual(parameters["color_temperature"]["overrides"]["calibration"]["set"], "5000")
        self.assertIn("colortemperature", parameters["color_temperature"]["mapping"]["sony"]["ids"])
        self.assertIn("/main/other/d01e", parameters["color_temperature"]["mapping"]["nikon"]["ids"])
        self.assertEqual(parameters["white_balance_adjust_ab"]["overrides"]["calibration"]["set"], "0")
        self.assertIn("whitebalanceadjusta", parameters["white_balance_adjust_ab"]["mapping"]["canon"]["ids"])
        self.assertIn("whitebalanceadjustgm", parameters["white_balance_adjust_gm"]["mapping"]["panasonic"]["ids"])
