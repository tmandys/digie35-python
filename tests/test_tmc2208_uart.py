"""python -m unittest discover -s tests -p test_tmc2208_uart.py

CRC oracle uses reflected table processing and final bit reversal, independently
of the driver's MSB accumulator. Reference: Analog Devices TMC-API,
tmc/ic/TMC2208/TMC2208.c (tmcCRCTable_Poly7Reflected and CRC8).
https://github.com/analogdevicesinc/TMC-API/blob/master/tmc/ic/TMC2208/TMC2208.c
"""
import unittest
from unittest.mock import patch

from digie35.tmc2208_uart import TMC2208UART, UARTError, crc8, read_request, _gconf_write


def reference_crc(data):
    table = []
    for value in range(256):
        for _ in range(8):
            value = (value >> 1) ^ (0xe0 if value & 1 else 0)
        table.append(value)
    # First entries from ADI's table also anchor the table generation.
    assert table[:8] == [0x00, 0x91, 0xe3, 0x72, 0x07, 0x96, 0xe4, 0x75]
    result = 0
    for byte in data:
        result = table[result ^ byte]
    return int(f"{result:08b}"[::-1], 2)


class SerialStub:
    baudrate = 19200
    def __init__(self, counter=0):
        self.pending = bytearray(b"stale bytes")
        self.registers = {0: 0x101, 2: counter, 6: 0x20000101, 0x6f: 0}
        self.sent = []
        self.mutate = lambda packet: packet
        self.accept_write = True
        self.short_write = False

    def reset_input_buffer(self):
        self.pending.clear()

    def write(self, data):
        self.sent.append(data)
        if self.short_write:
            return len(data) - 1
        packet = data
        if len(data) == 4 and data[0] == 5:
            reply = bytes((5, 255, data[2])) + self.registers[data[2]].to_bytes(4, "big")
            packet += reply + bytes((reference_crc(reply),))
        elif len(data) == 8:
            assert data[2] == 0x80  # The tool must never send OTP or other writes.
            assert reference_crc(data[:-1]) == data[-1]
            if self.accept_write:
                self.registers[0] = int.from_bytes(data[3:7], "big")
                self.registers[2] = (self.registers[2] + 1) & 255
        self.pending.extend(self.mutate(packet))
        return len(data)

    def read(self, size):
        # Every receive is fragmented into one-byte chunks.
        data = bytes(self.pending[:min(size, 1)])
        del self.pending[:len(data)]
        return data


class UARTTests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch("digie35.tmc2208_uart.time.sleep")
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def test_crc_and_packet_layout_against_reference(self):
        self.assertEqual(read_request(0), bytes.fromhex("05 00 00 48"))
        self.assertEqual(read_request(2), bytes.fromhex("05 00 02 8f"))
        for register in range(128):
            request = read_request(register)
            self.assertEqual(request[-1], reference_crc(request[:-1]))
        for value in (0, 1, 0x12345678, 0xffffffff):
            packet = _gconf_write(value)
            self.assertEqual(packet[:3], b"\x05\x00\x80")
            self.assertEqual(packet[3:7], value.to_bytes(4, "big"))
            self.assertEqual(packet[-1], reference_crc(packet[:-1]))
        for value in range(256):
            self.assertEqual(crc8(bytes([value])), reference_crc(bytes([value])))

    def test_loopback_and_fragmented_reply_discard_stale_bytes(self):
        port = SerialStub()
        uart = TMC2208UART(port)
        uart.loopback()
        self.assertEqual(port.sent, [bytes.fromhex("55 aa 12 34")])
        self.assertEqual(uart.read(6), 0x20000101)
        self.assertFalse(port.pending)

    def test_reject_bad_echo_header_register_crc_and_missing_data(self):
        mutations = [
            lambda p: b"\x00" + p[1:],  # bad echo
            lambda p: p[:4] + b"\x00" + p[5:],  # bad sync
            lambda p: p[:5] + b"\x00" + p[6:],  # slave instead of master
            lambda p: p[:6] + b"\x02" + p[7:],  # wrong register
            lambda p: p[:-1] + bytes((p[-1] ^ 1,)),  # corrupt CRC
            lambda p: p[:4],  # echo only
            lambda p: p[:-2],  # truncated response
            lambda p: b"",  # silent UART
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                port = SerialStub()
                port.mutate = mutation
                with self.assertRaises(UARTError):
                    TMC2208UART(port, timeout=0.005).read(6)

    def test_ifcnt_wraparound_and_unchanged_gconf(self):
        port = SerialStub(counter=255)
        self.assertEqual(TMC2208UART(port).probe_write(), (255, 0))
        self.assertEqual(port.registers[0], 0x101)
        self.assertEqual(sum(len(p) == 8 for p in port.sent), 1)

    def test_unaccepted_write_is_not_retried(self):
        port = SerialStub()
        port.accept_write = False
        with self.assertRaisesRegex(UARTError, "IFCNT"):
            TMC2208UART(port).probe_write()
        self.assertEqual(sum(len(p) == 8 for p in port.sent), 1)

    def test_enabled_or_wrong_chip_never_written(self):
        for inputs in (0x20000100, 0x21000101, 0x20000001):
            port = SerialStub()
            port.registers[6] = inputs
            with self.assertRaises(UARTError):
                TMC2208UART(port).probe_write()
            self.assertFalse(any(len(p) == 8 for p in port.sent))

    def test_short_write_is_error(self):
        port = SerialStub()
        port.short_write = True
        with self.assertRaisesRegex(UARTError, "Incomplete"):
            TMC2208UART(port).read(0)


if __name__ == "__main__":
    unittest.main()
