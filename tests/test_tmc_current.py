"""EEPROM current conversion and sleep sequencing without Raspberry Pi hardware."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from digie35.digie35board import (
    GulpStepperMotorAdapterMemory, GulpStepperMotorAdapter_0101,
)
from digie35.digie35core import DigitizerError


class CurrentTests(unittest.TestCase):
    def adapter(self, **overrides):
        custom = {field[0]: field[4] for field in GulpStepperMotorAdapterMemory.CUSTOM_MAP}
        custom["driver"] = GulpStepperMotorAdapterMemory.DRIVER_TMC2208_UART
        custom.update(overrides)
        memory = SimpleNamespace(get_adapter_custom=Mock(return_value=custom))
        return GulpStepperMotorAdapter_0101(SimpleNamespace(_aot_memory=memory))

    def test_current_scales_and_sense_range(self):
        # 100 mOhm + 30 mOhm: full scale is ~979 mA at 180 mV,
        # and ~1768 mA at 325 mV. Check independently rounded CS values.
        for run, hold, vsense, irun, ihold in (
            (700, 350, 1, 22, 10), (1200, 600, 0, 21, 10),
            (700, 900, 1, 22, 22), (1, 1, 1, 0, 0),
            (3000, 3000, 0, 31, 31),
        ):
            with self.subTest(run=run, hold=hold):
                adapter = self.adapter(run_current=run, hold_current=hold)
                self.assertEqual(adapter._tmc_vsense, vsense)
                self.assertEqual(adapter._tmc_ihold_irun, (4 << 16) | (irun << 8) | ihold)

    def test_missing_currents_and_unused_sense_resistor(self):
        for unset in (None, 0, 0xffff):
            adapter = self.adapter(run_current=unset, sensing_resistor=0xffff, hold_current=350)
            self.assertTrue(adapter._tmc_analog_current)
            self.assertEqual(adapter._tmc_ihold_irun, 0x41f1f)
            adapter = self.adapter(run_current=700, hold_current=unset)
            self.assertFalse(adapter._tmc_analog_current)
            self.assertEqual(adapter._tmc_ihold_irun & 31, (adapter._tmc_ihold_irun >> 8) & 31)
            with self.assertRaises(DigitizerError):
                self.adapter(run_current=700, sensing_resistor=unset)

    def registers(self, adapter, drop_register=None):
        registers = {0x6c: 0x14010055, 0x00: 0x18b, 0x02: 253}
        writes = []

        def transfer(register, value=None, mask=None):
            if value is None:
                # Current and power-down registers really are write-only.
                self.assertNotIn(register, (0x10, 0x11))
                return registers[register]
            if mask is not None:
                value = (value & mask) | (registers[register] & ~mask)
            writes.append((register, value))
            if register == drop_register:
                return
            if register in (0x00, 0x10, 0x11):
                self.assertEqual(registers[0x6c] & 15, 0)
            registers[register] = value
            registers[0x02] = (registers[0x02] + 1) & 255

        adapter._tmc_22xx_write_read = transfer
        return registers, writes

    def test_sleep_wake_preserves_toff_and_checks_counter_wrap(self):
        adapter = self.adapter(run_current=700, hold_current=350)
        registers, writes = self.registers(adapter)
        original = registers.copy()
        adapter._set_stepper_sleep("stepper_sleep", True)
        adapter._set_stepper_sleep("stepper_sleep", True)
        self.assertEqual(registers[0x6c] & 15, 0)
        adapter._set_stepper_sleep("stepper_sleep", False)
        self.assertEqual(registers[0x6c], original[0x6c] | (1 << 17))
        self.assertEqual(registers[0x00], (original[0x00] & ~0x43) | 0x40)
        self.assertEqual(registers[0x10], 0x4160a)
        self.assertEqual(registers[0x11], 20)
        self.assertEqual(writes[-1][0], 0x6c)
        self.assertEqual(writes[-1][1] & 15, 5)

    def test_analog_wake_restores_full_scale(self):
        adapter = self.adapter(run_current=0xffff)
        registers, _ = self.registers(adapter)
        registers[0x6c] |= 1 << 17
        adapter._set_stepper_sleep("stepper_sleep", False)
        self.assertEqual(registers[0x6c] & (1 << 17), 0)
        self.assertEqual(registers[0x00] & 0x43, 0x41)
        self.assertEqual(registers[0x10], 0x41f1f)

    def test_lost_current_write_leaves_outputs_disabled(self):
        adapter = self.adapter(run_current=700)
        registers, _ = self.registers(adapter, drop_register=0x10)
        with self.assertRaisesRegex(DigitizerError, "not accepted"):
            adapter._set_stepper_sleep("stepper_sleep", False)
        self.assertEqual(registers[0x6c] & 15, 0)

    def test_failed_disable_does_not_change_current(self):
        adapter = self.adapter(run_current=700)
        registers, writes = self.registers(adapter, drop_register=0x6c)
        with self.assertRaisesRegex(DigitizerError, "disable"):
            adapter._set_stepper_sleep("stepper_sleep", False)
        self.assertEqual(len(writes), 1)
        self.assertNotIn(0x10, registers)


if __name__ == "__main__":
    unittest.main()
