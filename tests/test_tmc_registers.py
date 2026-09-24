"""Register helpers tested without constructing a board or accessing hardware."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from digie35.digie35board import GulpStepperMotorAdapter, GulpStepperMotorAdapterMemory
from digie35.digie35core import DigitizerError
from tests.test_tmc2208_uart import reference_crc


def response(register, value):
    data = bytes((5, 255, register)) + value.to_bytes(4, "big")
    return data + bytes((reference_crc(data),))


class RegisterTests(unittest.TestCase):
    def setUp(self):
        # Bind only the two production methods: no board lifecycle or GPIO.
        class Helpers:
            _tmc_22xx_cal_crc = GulpStepperMotorAdapter._tmc_22xx_cal_crc
            _tmc_22xx_write_read = GulpStepperMotorAdapter._tmc_22xx_write_read
        self.adapter = Helpers()
        self.uart = Mock()
        self.adapter._xboard = SimpleNamespace(_mainboard=SimpleNamespace(uart_write_read=self.uart))

    def test_read_packet_and_big_endian_reply(self):
        self.uart.return_value = response(0, 0x12345678)
        self.assertEqual(self.adapter._tmc_22xx_write_read(0), 0x12345678)
        self.uart.assert_called_once_with(bytes.fromhex("05 00 00 48"), 8)

    def test_crc_against_independent_reference(self):
        for byte in range(256):
            data = bytes((5, 0, 0x80, byte, 0x12, 0x34, 0x56))
            self.assertEqual(self.adapter._tmc_22xx_cal_crc(data), reference_crc(data))

    def test_write_zero_and_big_endian_value(self):
        for value in (0, 0x12345678, 0xffffffff):
            self.uart.reset_mock()
            self.assertIsNone(self.adapter._tmc_22xx_write_read(0x6c, value))
            prefix = b"\x05\x00\xec" + value.to_bytes(4, "big")
            self.uart.assert_called_once_with(prefix + bytes((reference_crc(prefix),)), 0)

    def test_mask_preserves_unselected_bits_including_zero_mask(self):
        for mask, expected in ((0xf, 0x12345675), (0, 0x12345678), (0xffffffff, 5)):
            self.uart.reset_mock()
            self.uart.side_effect = [response(0x6c, 0x12345678), None]
            self.adapter._tmc_22xx_write_read(0x6c, 5, mask)
            self.assertEqual(self.uart.call_count, 2)
            packet, count = self.uart.call_args.args
            self.assertEqual(count, 0)
            self.assertEqual(int.from_bytes(packet[3:7], "big"), expected)
            self.assertEqual(packet[-1], reference_crc(packet[:-1]))

    def test_bad_replies_rejected_before_masked_write(self):
        valid = response(0x6c, 123)
        replies = [None, b"", valid[:-1], valid + b"x", response(0, 123),
                   b"\x04" + valid[1:], valid[:1] + b"\x00" + valid[2:],
                   valid[:6] + bytes((valid[6] ^ 1,)) + valid[7:]]
        for reply in replies:
            self.uart.reset_mock()
            self.uart.return_value = reply
            with self.assertRaises(DigitizerError):
                self.adapter._tmc_22xx_write_read(0x6c, 1, 0xf)
            self.assertEqual(self.uart.call_count, 1)

    def test_invalid_arguments_and_otp_never_transmitted(self):
        for args in ((128,), (-1,), (0, -1), (0, 1 << 32), (0, None, 1),
                     (0, 1, -1), (0, 1, 1 << 32), (4, 0xbd00)):
            with self.assertRaises(ValueError):
                self.adapter._tmc_22xx_write_read(*args)
        self.uart.assert_not_called()

    def test_uart_microsteps_preserve_other_settings(self):
        for exponent in range(9):
            registers = {0x6c: 0x30020053, 0x00: 0x141}
            original = registers.copy()
            def transfer(packet, count):
                register = packet[2] & 0x7f
                if count:
                    return response(register, registers[register])
                registers[register] = int.from_bytes(packet[3:7], "big")
            self.uart.side_effect = transfer
            self.adapter._DRIVER = GulpStepperMotorAdapterMemory.DRIVER_TMC2208_UART
            self.adapter._MICROSTEPPING = exponent
            self.adapter._REVERSE_DIR = False
            self.adapter._xboard.set_io_state = Mock()
            GulpStepperMotorAdapter._do_on_start(self.adapter, 1)
            # Match pulse resolution to the application's steps-per-mm scale.
            mres = (registers[0x6c] >> 24) & 15
            self.assertEqual(256 // (1 << mres), 1 << exponent)
            self.assertEqual(registers[0x6c] & (1 << 29), 0)
            self.assertEqual(registers[0x6c] & ~0x2f000000, original[0x6c] & ~0x2f000000)
            self.assertEqual(registers[0x00], original[0x00] | 0x80)


if __name__ == "__main__":
    unittest.main()
