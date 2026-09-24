"""Exercise the actual RpiMainboard methods with simulated serial and RPi imports."""
import importlib.util
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from digie35.digie35core import DigitizerError, ExtensionBoard


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Port:
    def __init__(self, clock, incoming=b"", echo=True):
        self.clock = clock
        self.incoming = incoming
        self.echo = echo
        self.buffer = bytearray(b"stale bytes")
        self.writes = []
        self.timeout = 0.25
        self.out_waiting = 0
        self.closed = False
        self.partial_write = False

    def reset_input_buffer(self):
        self.buffer.clear()

    def reset_output_buffer(self):
        self.out_waiting = 0

    def write(self, data):
        self.writes.append(data)
        self.buffer.extend((data if self.echo else b"") + self.incoming)
        return len(data) - int(self.partial_write)

    def read(self, count):
        if not self.buffer:
            self.clock.sleep(self.timeout)
            return b""
        chunk = bytes(self.buffer[:min(count, 2)])
        del self.buffer[:len(chunk)]
        return chunk

    def close(self):
        self.closed = True


class RpiUARTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load under a separate name so fake hardware imports cannot contaminate
        # other tests or any real mainboard module already imported by the runner.
        spec = importlib.util.spec_from_file_location(
            "rpi_uart_under_test", Path(__file__).resolve().parents[1] / "digie35/digie35rpi.py")
        cls.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "smbus2": SimpleNamespace(SMBus=Mock(), i2c_msg=Mock()),
            "rpi_hardware_pwm": SimpleNamespace(HardwarePWM=Mock()),
            "evdev": SimpleNamespace(InputDevice=Mock(), categorize=Mock(), ecodes=Mock(), list_devices=Mock()),
        }):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        self.clock = Clock()
        self.port = Port(self.clock)
        self.serial = SimpleNamespace(Serial=Mock(return_value=self.port),
                                      SerialException=OSError, EIGHTBITS=8,
                                      PARITY_NONE="N", STOPBITS_ONE=1)
        self.enterContext(patch.dict(sys.modules, {"serial": self.serial}))
        self.enterContext(patch.object(self.module, "time", self.clock))
        self.enterContext(patch.object(self.module.subprocess, "run", return_value=SimpleNamespace(
            stdout=b"Raspberry Pi 5", stderr=b"", returncode=0)))
        self.board = self.module.RpiMainboard(False)
        self.board.assign_extension_board(SimpleNamespace(_io_map={
            "tx": {"type": "uart", "dir": "o", "num": 14, "echo": True},
            "rx": {"type": "uart", "dir": "i", "num": 15},
        }))
        self.addCleanup(self.board.close_uart)

    def test_lazy_open_fragmented_echo_reply_and_reuse(self):
        self.serial.Serial.assert_not_called()
        self.port.incoming = b"reply123"
        for _ in range(2):
            self.assertEqual(self.board.uart_write_read([5, 0, 2, 143], 8), b"reply123")
        self.assertEqual(self.port.writes, [b"\x05\x00\x02\x8f"] * 2)
        self.serial.Serial.assert_called_once()
        options = self.serial.Serial.call_args.kwargs
        self.assertTrue(options["exclusive"])
        self.assertEqual(options["bytesize"], 8)
        self.assertGreater(options["write_timeout"], 0)

    def test_write_only_consumes_echo(self):
        self.assertEqual(self.board.uart_write_read(b"abcdefgh", 0), b"")
        self.assertEqual(self.port.buffer, b"")

    def test_echo_is_io_configuration_not_protocol(self):
        self.board._xboard._io_map["tx"]["echo"] = False
        self.port.echo = False
        self.port.incoming = b"OK"
        self.assertEqual(self.board.uart_write_read(b"hello", 2), b"OK")

    def test_wrong_echo_closes_port_without_retry(self):
        self.port.echo = False
        self.port.incoming = b"wrong"
        with self.assertRaisesRegex(DigitizerError, "echo"):
            self.board.uart_write_read(b"hello", 0)
        self.assertEqual(len(self.port.writes), 1)
        self.assertTrue(self.port.closed)
        self.assertIsNone(self.board._uart)

    def test_partial_response_and_missing_echo_timeout(self):
        self.port.incoming = b"ab"
        with self.assertRaisesRegex(DigitizerError, "2/8"):
            self.board.uart_write_read(b"request", 8)
        self.assertLess(self.clock.now, 0.3)
        self.port.echo = False
        self.port.incoming = b""
        with self.assertRaisesRegex(DigitizerError, "0/7"):
            self.board.uart_write_read(b"request", 0)

    def test_partial_write_never_retried(self):
        self.port.partial_write = True
        with self.assertRaisesRegex(DigitizerError, "incomplete write"):
            self.board.uart_write_read(b"request", 0)
        self.assertEqual(self.port.writes, [b"request"])

    def test_stalled_transmitter_is_bounded(self):
        self.board._xboard._io_map["tx"]["echo"] = False
        self.port.echo = False
        self.port.out_waiting = 1
        with self.assertRaisesRegex(DigitizerError, "transmit timeout"):
            self.board.uart_write_read(b"request", 0)
        self.assertLess(self.clock.now, 0.3)
        self.assertTrue(self.port.closed)

    def test_open_failure_and_lock_release(self):
        self.serial.Serial.side_effect = OSError("access denied")
        with self.assertRaisesRegex(DigitizerError, "access denied"):
            self.board.uart_write_read(b"x", 0)
        self.assertTrue(self.board._uart_lock.acquire(blocking=False))
        self.board._uart_lock.release()

    def test_concurrent_transactions_do_not_interleave(self):
        first_written = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        original_write = self.port.write
        errors = []

        def write(data):
            count = original_write(data)
            if data == b"first":
                first_written.set()
                if not release_first.wait(2):
                    raise RuntimeError("test did not release first transaction")
            return count

        def transaction(data):
            try:
                if data == b"second":
                    second_started.set()
                self.board.uart_write_read(data, 0)
            except Exception as exc:
                errors.append(exc)

        self.port.write = write
        first = threading.Thread(target=transaction, args=(b"first",))
        second = threading.Thread(target=transaction, args=(b"second",))
        first.start()
        try:
            self.assertTrue(first_written.wait(2))
            second.start()
            self.assertTrue(second_started.wait(2))
            self.assertEqual(self.port.writes, [b"first"])
        finally:
            release_first.set()
            first.join(2)
            if second.ident is not None:
                second.join(2)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.port.writes, [b"first", b"second"])

    def test_uart_pin_mapping_initialization_and_teardown(self):
        extension = self.board._xboard
        extension._mainboard = self.board
        for item in extension._io_map.values():
            item["_adapter_scope"] = False
        for is_pi5, function in ((True, "a4"), (False, "a0")):
            self.board._is_rpi5 = is_pi5
            ExtensionBoard._initialize_io_map(extension)
            command = "pinctrl" if is_pi5 else "raspi-gpio"
            self.module.subprocess.run.assert_any_call([command, "set", "14", function], check=True)
            self.module.subprocess.run.assert_any_call([command, "set", "15", function], check=True)
        self.board._is_rpi5 = True  # no GPIO destructor action on the test host
        self.board.uart_write_read(b"x", 0)
        ExtensionBoard._finalize_io_map(extension)
        self.assertTrue(self.port.closed)
        self.assertIsNone(self.board._uart)


if __name__ == "__main__":
    unittest.main()
