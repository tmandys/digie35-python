import tempfile
import unittest
from types import SimpleNamespace

from digie35.led_presets import LedPresets
from digie35.storage import LocalStorage


class LedPresetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.light = {"name":"Light", "adapter_class":"Test", "adapter_id":"RGB", "serial_number":"123"}
        self.caps = {"rgb_backlight":True,"white_backlight":True,"rgbaw_backlight":True}
        calibration = SimpleNamespace(digitizer=SimpleNamespace(get_capabilities=lambda:self.caps),
                                      light_identity=lambda mode:dict(self.light))
        self.manager = LedPresets(LocalStorage(tmp.name), calibration)
        self.settings = {"mode":"red+green+blue", "gains":{"red":1.2,"green":0.8,"blue":2},
                         "enabled":{"red":True,"green":False,"blue":True}, "exposure":1}

    def save(self, name="Test", identifier=None):
        return self.manager.save(name,self.settings,identifier,dict(self.light))

    def test_exposure_validation_and_legacy_presets(self):
        legacy = dict(self.settings)
        legacy.pop("exposure")
        self.assertNotIn("exposure", self.manager.settings(legacy))
        for value in (True, None, float("nan"), 3, -3, 0.2):
            with self.assertRaises(ValueError):
                self.manager.settings(dict(legacy, exposure=value))

    def test_create_update_reload_delete_and_exposure(self):
        saved = self.save()
        self.assertEqual(saved["exposure"],1)
        self.assertEqual(saved["gains"]["green"],0.8)
        self.assertFalse(saved["enabled"]["green"])
        self.settings["gains"]["red"] = 1.5
        updated = self.save("Renamed", saved["id"])
        self.assertEqual(updated["created_at"],saved["created_at"])
        self.assertEqual(self.manager.listing()["presets"][0]["gains"]["red"],1.5)
        self.manager.delete(saved["id"])
        self.assertEqual(self.manager.listing()["presets"],[])

    def test_names_ids_and_channels_are_validated(self):
        self.save()
        with self.assertRaises(ValueError): self.save(" test ")
        with self.assertRaises(ValueError): self.save("new","../escape")
        with self.assertRaises(ValueError): self.manager.delete("../escape")
        for value in [float('nan'), True, 0, 11]:
            self.settings["gains"]["red"] = value
            with self.assertRaises(ValueError): self.save("invalid")

    def test_light_identity_and_capabilities_filter_presets(self):
        saved = self.save()
        old = dict(self.light)
        self.light["serial_number"] = "456"
        self.assertEqual(self.manager.listing()["presets"],[])
        with self.assertRaises(ValueError): self.manager.save("x",self.settings,expected_light=old)
        with self.assertRaises(ValueError): self.manager.delete(saved["id"])
        self.light.update(old)
        self.caps.clear()
        self.assertEqual(self.manager.listing()["presets"],[])
        with self.assertRaises(ValueError): self.save("x")

    def test_empty_modes_and_bad_files(self):
        self.manager.storage.save("led_presets","bad",{})
        with self.assertLogs(level="WARNING"):
            self.assertEqual(self.manager.listing()["presets"],[])


if __name__ == "__main__": unittest.main()
