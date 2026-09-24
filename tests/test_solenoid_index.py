"""Model STEP edges and UART registers; no Raspberry Pi or motor required."""
import itertools
import unittest
from unittest.mock import patch

from digie35.digie35board import GulpStepperMotorAdapter_0105, GulpStepperMotorAdapterMemory
from digie35.digie35core import DigitizerError


class Model:
    _do_pull_selenoid = GulpStepperMotorAdapter_0105._do_pull_selenoid
    _tmc_22xx_restore_index = GulpStepperMotorAdapter_0105._tmc_22xx_restore_index
    _SELENOID = True
    _DRIVER = GulpStepperMotorAdapterMemory.DRIVER_TMC2208_UART

    def __init__(self, exponent=4, step=False, dir_inverted=False, step_inverted=False, shaft=False):
        self._MICROSTEPPING = exponent
        self._xboard = self
        self.props = dict(FP_BACKLIGHT_OFF=False, FP_DOWN_COUNT=1,
                          FP_PULSE_WIDTH=0, FP_PWM_FREQ=0, FP_PWM_RATIO=0.8, FP_PULSE_COUNT=3)
        self.state = dict(stepper_enable=True, stepper_step=step, stepper_dir=False)
        self.dir_inverted = dir_inverted
        self.step_inverted = step_inverted
        self.registers = {0: 0x80 | (8 if shaft else 0), 0x6c: ((8-exponent) << 24) | (1 << 28) | 0x20053}
        self.ms_pins = 0
        self.index = (256 >> exponent) // 2
        self.original_index = self.index
        self.initial_registers = self.registers.copy()
        self._flattening_state = False
        self._last_flattening_change = None
        self.events = []
        self.index_reads = 0
        self.drop_correction_edge = False
        self.fail_second_index_read = False
        self.ignore_interpolation_write = False

    def get_io_state(self, name):
        return self.state[name]

    def set_io_state(self, name, value):
        self.events.append((name, value))
        if name == "stepper_step":
            old = bool(self.state[name]) ^ self.step_inverted
            new = bool(value) ^ self.step_inverted
            if not old and new:
                if self.drop_correction_edge and self.index_reads >= 2:
                    self.drop_correction_edge = False
                else:
                    if self.registers[0] & 0x80:
                        increment = 1 << ((self.registers[0x6c] >> 24) & 15)
                    else:
                        increment = (32, 128, 64, 16)[self.ms_pins]
                    decreasing = bool(self.state["stepper_dir"]) ^ self.dir_inverted ^ bool(self.registers[0] & 8)
                    self.index = (self.index + (-increment if decreasing else increment)) % 1024
        if name == "stepper_enable" and value:
            # Catch any premature re-enable at the wrong electrical position.
            if self.index != self.original_index:
                raise AssertionError("Motor enabled before index restoration")
        self.state[name] = value

    def _precise_sleep(self, seconds):
        self.events.append(("delay", seconds))

    def _tmc_22xx_write_read(self, register, value=None, mask=None):
        if value is not None:
            if not self.ignore_interpolation_write:
                self.registers[register] = ((self.registers[register] & ~mask) | (value & mask)) if mask is not None else value
            return
        if register == 0x06:
            return (int(not self.state["stepper_enable"]) | (self.ms_pins << 2) |
                    ((bool(self.state["stepper_dir"]) ^ self.dir_inverted) << 9))
        if register == 0x6a:
            self.index_reads += 1
            if self.fail_second_index_read and self.index_reads == 2:
                raise DigitizerError("simulated UART timeout")
            return self.index
        return self.registers[register]


class SolenoidIndexTests(unittest.TestCase):
    def setUp(self):
        sleep = patch("digie35.digie35board.time.sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_roundtrip_resolutions_directions_and_inversions(self):
        for args in itertools.product(range(9), (False, True), (False, True), (False, True), (False, True)):
            with self.subTest(args=args):
                model = Model(*args)
                initial = model.state.copy()
                model._do_pull_selenoid(True)
                self.assertEqual(model.index, model.original_index)
                self.assertEqual(model.state, initial)
                self.assertEqual(model.registers, model.initial_registers)
                self.assertTrue(model._flattening_state)
                self.assertGreaterEqual(model.index_reads, 4)

    def test_pin_resolution_before_first_uart_microstep_setup(self):
        for pins in range(4):
            model = Model()
            model.registers[0] &= ~0x80
            model.ms_pins = pins
            model._do_pull_selenoid(False)
            self.assertEqual(model.index, model.original_index)
            self.assertTrue(model.state["stepper_enable"])

    def test_dropped_correction_edge_leaves_motor_and_solenoid_off(self):
        model = Model()
        model.drop_correction_edge = True
        with self.assertRaisesRegex(DigitizerError, "restore failed"):
            model._do_pull_selenoid(True)
        self.assertFalse(model.state["stepper_enable"])
        self.assertFalse(model.state["stepper_step"])
        self.assertIsNone(model._flattening_state)
        self.assertNotIn(("stepper_enable", True), model.events)

    def test_uart_failure_leaves_motor_and_solenoid_off(self):
        model = Model()
        model.fail_second_index_read = True
        with self.assertRaisesRegex(DigitizerError, "UART timeout"):
            model._do_pull_selenoid(True)
        self.assertFalse(model.state["stepper_enable"])
        self.assertFalse(model.state["stepper_step"])

    def test_failed_interpolation_disable_prevents_pwm(self):
        model = Model()
        model.ignore_interpolation_write = True
        with self.assertRaisesRegex(DigitizerError, "interpolation"):
            model._do_pull_selenoid(True)
        self.assertNotIn(("stepper_step", True), model.events)
        self.assertFalse(model.state["stepper_enable"])

    def test_unreachable_index_does_not_round_or_pulse(self):
        model = Model()
        model.state["stepper_enable"] = False
        with self.assertRaisesRegex(DigitizerError, "unreachable"):
            model._tmc_22xx_restore_index(model.index + 1, False, model.registers[0x6c] & ~(1 << 28))
        self.assertEqual(model.events, [])

    def test_already_correct_index_requires_no_pulses(self):
        model = Model()
        model.state["stepper_enable"] = False
        model._tmc_22xx_restore_index(model.index, False, model.registers[0x6c] & ~(1 << 28))
        self.assertEqual(model.events, [])


if __name__ == "__main__":
    unittest.main()
