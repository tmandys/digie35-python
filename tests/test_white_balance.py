import asyncio
import copy
from pathlib import Path
import tempfile
import unittest

from digie35.color_profiles import ColorProfiles
from digie35.storage import LocalStorage
from digie35.white_balance import WhiteBalance


class WhiteBalanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        profiles = ColorProfiles(LocalStorage(tmp.name), Path(tmp.name) / "builtin")
        class Light:
            def __init__(self):
                self.light = {"color":"white+red+green+blue", "exposure":0, "temp":5000,
                              "gain":{"white":0.2, "red":1, "green":1, "blue":1}}
            def get_state(self): return {"backlight":copy.deepcopy(self.light)}
            def set_backlight(self, **settings): self.light = copy.deepcopy(settings)
            def get_adapter(self, name): return None
            def get_capabilities(self): return {"rgb_backlight":True, "white_backlight":True}
            def get_backlight_pwm_status(self, **settings):
                return {c:{"actual":int(g*25), "clipped":g>4} for c,g in settings["gain"].items()}
        self.light = Light()
        self.original = copy.deepcopy(self.light.light)
        self.wb = WhiteBalance(self.light, profiles)
        self.owner = object()
        self.matrix = [[20,80,8,2], [20,5,85,6], [20,2,7,90]]
        self.profile = {"schema_version":1, "name":"Test", "channels":["white","red","green","blue"],
                        "matrix":self.matrix, "units":"preview_rgb_per_channel_gain",
                        "light":self.wb.light_identity(self.original["color"])}
        self.profile_id = profiles.save(self.profile)["id"]

    async def asyncTearDown(self):
        self.wb.disconnect(self.owner)

    def begin(self):
        return self.wb.begin(self.owner, self.profile_id, "usb|Test camera")["token"]

    def rgb(self, film=(0.55,0.8,1), gamma=1):
        gains = self.light.light["gain"]
        return [(sum(v*gains.get(c, 0) for v,c in zip(row,self.profile["channels"])) * attenuation) ** gamma
                for row,attenuation in zip(self.matrix,film)]

    async def test_converges_through_film_with_crosstalk_and_keeps_ev(self):
        for gamma in (1, 0.85):
            self.light.light = copy.deepcopy(self.original)
            token = self.begin()
            for _ in range(17):
                result = self.wb.step(self.owner, token, self.rgb(gamma=gamma))
                self.assertNotIn("error", result)  # Reserved by the WebSocket RPC transport.
                self.assertIn("imbalance", result)
                if result["done"]: break
            self.assertTrue(result["done"])
            self.wb.end(self.owner, token, True)
            self.assertEqual(self.light.light["exposure"], self.original["exposure"])
            self.assertGreater(self.light.light["gain"]["white"], 0)
            self.assertEqual(self.light.light["temp"], 5000)
            self.assertLess(max(self.rgb()) - min(self.rgb()), 4)

    async def test_white_is_reduced_when_it_dominates_red(self):
        self.matrix = [[100,20,0,0], [30,0,40,0], [20,0,0,40]]
        self.profile.update(name="Dominant white", matrix=self.matrix)
        self.profile_id = self.wb.profiles.save(self.profile)["id"]
        self.light.light["gain"]["white"] = 1
        token = self.begin()
        self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
        self.assertLess(self.light.light["gain"]["white"], 1)
        for _ in range(16):
            result = self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
            if result["done"]: break
        self.assertTrue(result["done"])

    async def test_both_whites_participate_but_disabled_white_stays_off(self):
        self.light.get_capabilities = lambda: {"rgbaw_backlight":True, "rgb_backlight":True, "white_backlight":True}
        self.light.light["color"] = "amber+white+red+green+blue"
        self.light.light["gain"].update(amber=1, white=1)
        self.matrix = [[100,80,20,0,0], [20,30,0,40,0], [10,20,0,0,40]]
        self.profile.update(name="Two whites", channels=["amber","white","red","green","blue"], matrix=self.matrix)
        self.profile_id = self.wb.profiles.save(self.profile)["id"]
        token = self.begin()
        self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
        self.assertNotEqual(self.light.light["gain"]["white"], 1)
        self.assertLess(self.light.light["gain"]["amber"], 1)
        self.wb.end(self.owner, token)
        self.light.light["gain"].update(amber=0, white=0)
        token = self.begin()
        self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
        self.assertEqual(self.light.light["gain"]["white"], 0)
        self.assertEqual(self.light.light["gain"]["amber"], 0)

    async def test_limited_blue_is_balanced_by_dimming_other_channels(self):
        self.light.light.update(color="red+green+blue", gain={"red":2,"green":2,"blue":4})
        self.matrix = [[0,40,0,0], [0,0,40,0], [0,0,0,10]]
        self.profile.update(name="Limited blue", matrix=self.matrix)
        self.profile_id = self.wb.profiles.save(self.profile)["id"]
        token = self.begin()
        first = self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
        self.assertLess(first["settings"]["gain"]["red"], 2)
        self.assertLess(first["settings"]["gain"]["green"], 2)
        self.assertLessEqual(first["settings"]["gain"]["blue"], 4)
        for _ in range(16):
            result = self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
            if result["done"]: break
        self.assertTrue(result["done"])
        self.assertLess(sum(self.rgb(film=(1,1,1))) / 3, 50)

    async def test_white_reduction_is_not_throttled_by_saturated_gb(self):
        self.matrix = [[100,20,0,0], [10,0,10,0], [10,0,0,10]]
        self.profile.update(name="Saturated GB", matrix=self.matrix)
        self.profile_id = self.wb.profiles.save(self.profile)["id"]
        self.light.light["gain"].update(white=1, red=1, green=4, blue=4)
        token = self.begin()
        self.wb.step(self.owner, token, self.rgb(film=(1,1,1)))
        self.assertLess(self.light.light["gain"]["white"], 0.85)
        self.assertTrue(all(g <= 4 for g in self.light.light["gain"].values()))

    async def test_already_clipped_gain_recovers_without_changing_ev(self):
        self.light.light["gain"]["red"] = 5
        token = self.begin()
        self.wb.step(self.owner, token, [180,100,100])
        self.assertLessEqual(self.light.light["gain"]["red"], 4)
        self.assertEqual(self.light.light["exposure"], 0)

    async def test_partial_keep_requires_explicit_flag_and_releases_session(self):
        token = self.begin()
        self.wb.step(self.owner, token, self.rgb())
        current = copy.deepcopy(self.light.light)
        with self.assertRaises(ValueError): self.wb.end(self.owner, token, commit=True)
        result = self.wb.end(self.owner, token, commit=True, keep_partial=True)
        self.assertTrue(result["partial"])
        self.assertFalse(result["restored"])
        self.assertEqual(self.light.light, current)
        self.assertIsNone(self.wb.session)
        next_token = self.begin()
        self.assertEqual(self.wb.session["original"], current)
        self.wb.end(self.owner, next_token)

    async def test_cancel_disconnect_timeout_restore_and_late_steps_fail(self):
        for finish in ("cancel", "disconnect", "timeout"):
            token = self.begin()
            self.wb.step(self.owner, token, self.rgb())
            self.assertNotEqual(self.light.light, self.original)
            if finish == "cancel": self.wb.end(self.owner, token)
            elif finish == "disconnect": self.wb.disconnect(self.owner)
            else:
                self.wb.TIMEOUT = 0.01
                self.wb._touch()
                await asyncio.sleep(0.03)
            self.assertEqual(self.light.light, self.original)
            self.assertIsNone(self.wb.session)
            with self.assertRaises(ValueError): self.wb.step(self.owner, token, [100]*3)

    async def test_measured_profile_with_negative_cross_channel_terms(self):
        self.matrix = [[45.1882,12.6296,-7.4203,1.2004], [44.7758,-0.8338,16.3431,0.4584],
                       [37.8628,-1.4446,5.1218,30.1440]]
        baseline = [64.281,77.318,95.495]
        self.profile.update({"name":"Measured response", "matrix":self.matrix,
                             "baseline":{"rgb":baseline, "settings":{"gain":{c:1 for c in self.profile["channels"]}}}})
        self.profile_id = self.wb.profiles.save(self.profile)["id"]
        self.light.light["gain"]["white"] = 1
        token = self.begin()
        for _ in range(17):
            gains = self.light.light["gain"]
            rgb = [(baseline[r] + sum(row[j]*(gains[c]-1) for j,c in enumerate(self.profile["channels"]))) * film
                   for r,(row,film) in enumerate(zip(self.matrix,[0.85,0.95,1]))]
            result = self.wb.step(self.owner, token, rgb)
            if result["done"]: break
        self.assertTrue(result["done"])
        self.assertNotEqual(self.light.light["gain"]["white"],1)
        self.wb.end(self.owner, token, True)

    async def test_ownership_and_commit_require_convergence(self):
        token = self.begin()
        with self.assertRaises(ValueError): self.wb.begin(object(), self.profile_id, "camera")
        with self.assertRaises(ValueError): self.wb.step(object(), token, [100]*3)
        with self.assertRaises(ValueError): self.wb.end(self.owner, token, True)
        self.assertEqual(self.light.light, self.original)

    async def test_invalid_samples_do_not_change_light(self):
        token = self.begin()
        for rgb in ([0,100,100], [255]*3, [float("nan")]*3, [True]*3, [100], None):
            with self.assertRaises(ValueError): self.wb.step(self.owner, token, rgb)
        self.assertEqual(self.light.light, self.original)

    async def test_invalid_mode_disabled_channel_wrong_profile_and_camera(self):
        for change in ("mode", "identity", "camera"):
            self.light.light = copy.deepcopy(self.original)
            if change == "mode": self.light.light["color"] = "white"
            elif change == "identity":
                bad = copy.deepcopy(self.profile)
                bad["name"] = "Wrong light"
                bad["light"]["adapter_class"] = "Different"
                self.profile_id = self.wb.profiles.save(bad)["id"]
            with self.assertRaises(ValueError):
                self.wb.begin(self.owner, self.profile_id, "" if change == "camera" else "camera")
            self.assertIsNone(self.wb.session)

    async def test_disabled_rgb_channels_are_enabled_and_restored_on_cancel(self):
        self.light.light["gain"].update(red=0, blue=0)
        original = copy.deepcopy(self.light.light)
        session = self.wb.begin(self.owner, self.profile_id, "camera", {"red":1.7,"green":3,"blue":0.8})
        self.assertEqual(self.light.light["gain"], {"white":0.2,"red":1.7,"green":1,"blue":0.8})
        self.wb.end(self.owner, session["token"])
        self.assertEqual(self.light.light, original)
        with self.assertRaises(ValueError):
            self.wb.begin(self.owner, self.profile_id, "camera", {"red":float("nan")})
        self.assertEqual(self.light.light, original)

    async def test_pwm_limit_and_no_progress_are_bounded(self):
        token = self.begin()
        with self.assertRaises(ValueError):
            for _ in range(17): self.wb.step(self.owner, token, [30,100,130])
        self.assertTrue(all(v <= 4 for v in self.light.light["gain"].values()))
        self.wb.end(self.owner, token)
        self.assertEqual(self.light.light, self.original)


if __name__ == "__main__": unittest.main()
