"""Run: python -m unittest discover -s tests -p test_color_profiles.py"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest

from digie35.color_profiles import BacklightCalibration, ColorProfiles
from digie35.storage import LocalStorage


def profile(name="Test profile"):
    return {"schema_version": 1, "name": name, "channels": ["red", "green", "blue"],
            "units": "preview_rgb_per_channel_gain",
            "matrix": [[1, 0.1, 0], [0, 1, 0], [0, 0, 1]]}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.builtin = self.root / "package"
        self.builtin.mkdir()
        self.storage = LocalStorage(self.root / "user")
        self.profiles = ColorProfiles(self.storage, self.builtin)

    def test_merge_portable_files_and_builtin_protection(self):
        (self.builtin / "default.json").write_text(json.dumps(profile("Factory")))
        saved = self.profiles.save(profile("Moje světlo"))
        listing = self.profiles.list()["profiles"]
        self.assertEqual({r["source"] for r in listing}, {"builtin", "user"})
        self.assertEqual(self.profiles.get(saved["id"])["profile"]["name"], "Moje světlo")
        with self.assertRaises(ValueError):
            self.profiles.delete("builtin:default")
        copied = json.loads(next((self.storage.directory / "color_profiles").glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(copied["matrix"], profile()["matrix"])
        self.profiles.delete(saved["id"])
        self.assertEqual(len(self.profiles.list()["profiles"]), 1)

    def test_duplicate_names_are_checked_on_save_as_well_as_before_calibration(self):
        self.profiles.check_name("My light")
        self.profiles.save(profile(" My light "))
        for name in ("My light", "MY LIGHT", " my light "):
            with self.assertRaises(ValueError): self.profiles.check_name(name)
            with self.assertRaises(ValueError): self.profiles.save(profile(name))
        self.assertEqual(len(self.profiles.list()["profiles"]), 1)

    def test_invalid_profiles_and_missing_ids(self):
        for value in (None, {}, profile("") | {"matrix": []}, profile() | {"matrix": [[float('nan')]*3]*3}):
            with self.assertRaises((TypeError, ValueError)):
                self.profiles.save(value)
        with self.assertRaises(ValueError): self.profiles.delete("user:../../outside")
        (self.builtin / "broken.json").write_text("{")
        with self.assertLogs(level="WARNING"):
            self.assertEqual(self.profiles.list(), {"profiles": []})


class CalibrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        profiles = ColorProfiles(LocalStorage(tmp.name), Path(tmp.name) / "builtin")
        self.original = {"color": "white+red+green+blue", "exposure": -1,
                         "gain": {"white": 1, "red": 1, "green": 0.8, "blue": 0.7}, "temp": 4200}
        class Digitizer:
            light = copy.deepcopy(self.original)
            def get_state(self): return {"backlight": copy.deepcopy(self.light)}
            def set_backlight(self, **settings): self.light = settings
            def get_adapter(self, name): return None
            def get_capabilities(self): return {"white_backlight": True, "rgb_backlight": True}
        self.digitizer = Digitizer()
        self.calibration = BacklightCalibration(self.digitizer, profiles)
        self.owner = object()

    async def asyncTearDown(self):
        self.calibration.disconnect(self.owner)

    async def test_steps_restore_other_channels_and_original_temperature(self):
        start = self.calibration.begin(self.owner, "Test")
        token = start["token"]
        self.calibration.step(self.owner, token, "red", 0.8)
        self.assertEqual(self.digitizer.light["gain"]["red"], 0.8)
        self.calibration.step(self.owner, token, "green", 1.2)
        self.assertEqual(self.digitizer.light["gain"]["red"], 1)
        self.calibration.end(self.owner, token)
        self.assertEqual(self.digitizer.light, self.original)
        self.assertIsNone(self.calibration.timer)

    async def test_ownership_disconnect_and_late_steps(self):
        token = self.calibration.begin(self.owner, "Test")["token"]
        with self.assertRaises(ValueError): self.calibration.begin(object(), "Other")
        with self.assertRaises(ValueError): self.calibration.step(object(), token, "red", 0.8)
        self.calibration.disconnect(object())
        self.assertIsNotNone(self.calibration.session)
        self.calibration.step(self.owner, token, "red", 0.8)
        self.calibration.disconnect(self.owner)
        self.assertEqual(self.digitizer.light, self.original)
        with self.assertRaises(ValueError): self.calibration.step(self.owner, token, "red", 1.2)

    async def test_expiry_restores_light(self):
        self.calibration.TIMEOUT = 0.01
        token = self.calibration.begin(self.owner, "Test")["token"]
        self.calibration.step(self.owner, token, "blue", 0.8)
        await asyncio.sleep(0.03)
        self.assertIsNone(self.calibration.session)
        self.assertEqual(self.digitizer.light, self.original)

    async def test_pwm_headroom_selects_safe_ev_and_restores_original(self):
        from digie35.digie35board import GulpGeneralLight8xPWMAdapter
        class Light:
            _default_pwm_0ev = {"white":255 / 2**2.5}
            def get_backlight_pwm_status(self, **settings):
                return GulpGeneralLight8xPWMAdapter.get_backlight_pwm_status(self, **settings)
        light = Light()
        self.digitizer.get_adapter = lambda name: light
        self.digitizer.light["exposure"] = 2.5
        self.original["exposure"] = 2.5
        session = self.calibration.begin(self.owner, "Test")
        self.assertEqual(session["base"]["exposure"], 2)
        self.assertNotIn(2.5, session["exposure_options"])
        with self.assertRaises(ValueError): self.calibration.step(self.owner, session["token"], exposure=2.5)
        self.calibration.step(self.owner, session["token"], exposure=1)
        self.assertEqual(self.calibration.session["base"]["exposure"], 1)
        self.calibration.end(self.owner, session["token"])
        self.assertEqual(self.digitizer.light, self.original)

    async def test_auto_ev_rejects_invalid_values_and_keeps_original_for_disconnect(self):
        session = self.calibration.begin(self.owner, "Test")
        for ev in [True, float('nan'), 100, -100, 0.1]:
            with self.assertRaises(ValueError): self.calibration.step(self.owner, session["token"], exposure=ev)
        with self.assertRaises(ValueError): self.calibration.step(self.owner, session["token"], 'red', 1.2, exposure=1)
        self.calibration.step(self.owner, session["token"], exposure=1)
        self.calibration.disconnect(self.owner)
        self.assertEqual(self.digitizer.light, self.original)

    async def test_saved_profile_uses_final_auto_ev_not_original_ev(self):
        session = self.calibration.begin(self.owner, "Auto EV")
        self.calibration.step(self.owner, session["token"], exposure=1.5)
        self.calibration.end(self.owner, session["token"])
        data = profile() | {"channels": session["channels"], "matrix": [[1]*4]*3,
                            "baseline": {"settings": {"exposure":99}}}
        saved = self.calibration.save_profile(self.owner, session["token"], data)
        actual = self.calibration.profiles.get(saved["id"])["profile"]
        self.assertEqual(actual["baseline"]["settings"]["exposure"], 1.5)
        self.assertEqual(self.digitizer.light, self.original)

    async def test_bad_steps_are_rejected_without_changing_light(self):
        token = self.calibration.begin(self.owner, "Test")["token"]
        for channel, factor in [("ir", 1), ("red", 100), ("red", float("nan"))]:
            with self.assertRaises(ValueError): self.calibration.step(self.owner, token, channel, factor)
        self.assertEqual(self.digitizer.light, self.original)

    async def test_automatic_white_mode_and_restore_original(self):
        self.digitizer.get_capabilities = lambda: {"white_backlight": True}
        token = self.calibration.begin(self.owner, "White")["token"]
        self.calibration.step(self.owner, token)
        self.assertEqual(self.digitizer.light["color"], "white")
        self.assertEqual(self.digitizer.light["gain"], {"white": 1})
        self.calibration.end(self.owner, token)
        self.assertEqual(self.digitizer.light, self.original)
        self.digitizer.get_capabilities = lambda: {"ir_backlight": True}
        with self.assertRaises(ValueError): self.calibration.begin(self.owner, "IR")

    async def test_capabilities_choose_all_available_visible_channels(self):
        for caps, expected in [
            ({"rgbaw_backlight": True}, "amber+white+red+green+blue"),
            ({"rgbaw_backlight": True, "rgb_backlight": True, "white_backlight": True}, "amber+white+red+green+blue"),
            ({"rgb_backlight": True, "white_backlight": True}, "white+red+green+blue"),
            ({"rgb_backlight": True}, "red+green+blue"),
            ({"white_backlight": True}, "white"),
        ]:
            with self.subTest(caps=caps):
                self.digitizer.get_capabilities = lambda: caps
                info = self.calibration.info()
                session = self.calibration.begin(self.owner, "Test")
                self.assertEqual(info["mode"], expected)
                self.assertEqual(session["channels"], expected.split("+"))
                self.assertEqual(session["base"]["color"], expected)
                self.calibration.end(self.owner, session["token"])

    async def test_server_records_actual_eeprom_identity_and_full_precision_serial(self):
        header = {"human_name": "Medium format LB", "adapter_id": "MAN120", "version": 103,
                  "serial_number": 12345678901234567890}
        class Light:
            def get_memory(self): return self
            def read_header(self): return header
        light = Light()
        self.digitizer.get_adapter = lambda name: light
        session = self.calibration.begin(self.owner, "Test")
        self.assertEqual(session["light"]["name"], "Medium format LB")
        self.assertEqual(session["light"]["serial_number"], "12345678901234567890")
        self.calibration.end(self.owner, session["token"])
        data = profile() | {"channels": session["channels"], "matrix": [[1]*4]*3,
                            "baseline": {"settings": {}}, "light": {"name": "forged"}}
        saved = self.calibration.save_profile(self.owner, session["token"], data)
        actual = self.calibration.profiles.get(saved["id"])["profile"]
        self.assertEqual(actual["light"], session["light"])
        self.assertEqual(actual["baseline"]["settings"], session["base"])
        header["serial_number"] = 0
        self.assertIsNone(self.calibration.light_identity("white")["serial_number"])

    async def test_hotplug_stops_calibration_without_applying_old_settings_to_new_light(self):
        class Light:
            pass
        self.digitizer.get_adapter = lambda name: old
        old = Light()
        session = self.calibration.begin(self.owner, "Test")
        self.digitizer.get_adapter = lambda name: Light()
        with self.assertRaisesRegex(ValueError, "light changed"):
            self.calibration.step(self.owner, session["token"])
        with self.assertRaisesRegex(ValueError, "light changed"):
            self.calibration.end(self.owner, session["token"])
        self.assertIsNone(self.calibration.session)


if __name__ == "__main__":
    unittest.main()
