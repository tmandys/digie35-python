import unittest
from types import SimpleNamespace

from digie35.digie35board import GulpGeneralLight8xPWMAdapter, pwm_from_exposure
from digie35.digie35core import ExtensionBoard


class BacklightPwmTests(unittest.TestCase):
    def test_manual120_white_limit_and_clipping(self):
        for gain, expected, clipped in [(0.8, 204, False), (1, 255, False), (1.2, 255, True)]:
            status = {}
            output = pwm_from_exposure(["white"], 2.5, {"white": gain},
                                       {"white": 255 / 2**2.5}, diagnostics=status)
            self.assertEqual(output["white"], expected)
            self.assertEqual(status["white"]["clipped"], clipped)
            self.assertEqual(status["white"]["at_limit"], expected == 255)

    def test_raw_gain_and_off_channel(self):
        status = {}
        pwm_from_exposure(["red", "blue"], None, {"red": 1.2, "blue": 0}, diagnostics=status)
        self.assertTrue(status["red"]["clipped"])
        self.assertEqual(status["blue"]["actual"], 0)
        self.assertFalse(status["blue"]["at_limit"])

    def test_status_is_in_backlight_state_and_clears_when_off(self):
        light = SimpleNamespace(_default_pwm_0ev={"white": 255 / 2**2.5}, get_state=lambda: {})
        light.get_backlight_pwm_status = lambda **kw: GulpGeneralLight8xPWMAdapter.get_backlight_pwm_status(light, **kw)
        board = SimpleNamespace(_get_xio=lambda force: None, get_io_states=lambda: {},
                                _current_backlight_color="white", _save_backlight_exposure={"white":2.5},
                                _save_backlight_gain={"white":{"white":1.2}}, _adapters={"light":light},
                                get_adapter=lambda name: light)
        self.assertTrue(ExtensionBoard.get_state(board)["backlight"]["pwm"]["white"]["clipped"])
        board._current_backlight_color = None
        self.assertEqual(ExtensionBoard.get_state(board)["backlight"]["pwm"], {})

    def test_min_distinguishes_small_positive_pwm_from_intentional_off(self):
        for exposure, gain, expected in [(None, 0, False), (None, 0.001, True),
                                          (None, 1/255, False), (-8, 1, True),
                                          (-8, 0, False), (-5, 1, False)]:
            with self.subTest(exposure=exposure, gain=gain):
                status = {}
                pwm_from_exposure(["red"], exposure, {"red":gain}, diagnostics=status)
                self.assertEqual(status["red"]["at_min"], expected)
        status = {}
        pwm_from_exposure(["red"], None, 0, diagnostics=status)
        self.assertFalse(status["red"]["at_min"])


if __name__ == "__main__":
    unittest.main()
