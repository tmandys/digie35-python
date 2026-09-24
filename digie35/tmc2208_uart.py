"""Standalone TMC2208 UART diagnostics; STEP/DIR and GPIO are never driven here."""
import argparse
import math
import threading
import time


GCONF = 0x00
IFCNT = 0x02
IOIN = 0x06


class UARTError(RuntimeError):
    pass


def crc8(data):
    """TMC UART CRC: polynomial 0x07, input bits LSB first, initial value 0."""
    crc = 0
    for byte in data:
        for _ in range(8):
            feedback = (crc >> 7) ^ (byte & 1)
            crc = ((crc << 1) ^ (0x07 if feedback else 0)) & 0xff
            byte >>= 1
    return crc


def read_request(register):
    if not 0 <= register <= 0x7f:
        raise ValueError("Register must be between 0x00 and 0x7f")
    data = bytes((0x05, 0x00, register))
    return data + bytes((crc8(data),))


def _gconf_write(value):
    # Deliberately no arbitrary write-register API (in particular no OTP_PROG).
    data = bytes((0x05, 0x00, GCONF | 0x80)) + value.to_bytes(4, "big")
    return data + bytes((crc8(data),))


class TMC2208UART:
    """Single owner of a pyserial-compatible port with physically connected TX/RX.

    The port must have finite read/write timeouts. Each transaction consumes its
    exact echo, then (for reads) a separately validated response. No write retries.
    """
    def __init__(self, port, timeout=0.25, trace=None):
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be positive and finite")
        if not port.baudrate or port.baudrate <= 0:
            raise ValueError("Baud rate must be positive")
        self.port = port
        self.timeout = timeout
        self.port.timeout = min(timeout, 0.02)
        self.port.write_timeout = timeout
        self.trace = trace or (lambda direction, data: None)
        self.lock = threading.RLock()

    def _receive(self, length, deadline):
        data = bytearray()
        while len(data) < length:
            if time.monotonic() >= deadline:
                raise UARTError(f"Timeout: received {len(data)}/{length} bytes: {data.hex(' ')}")
            chunk = self.port.read(length - len(data))
            if chunk:
                self.trace("RX", chunk)
                data.extend(chunk)
        return bytes(data)

    def _send(self, data):
        # Allow the driver to release the line / discard an incomplete datagram.
        # Also accommodates an old reply after a previous timeout.
        time.sleep(320 / self.port.baudrate)
        self.port.reset_input_buffer()
        self.trace("TX", data)
        deadline = time.monotonic() + self.timeout
        if self.port.write(data) != len(data):
            raise UARTError("Incomplete UART write; transaction not retried")
        echo = self._receive(len(data), deadline)
        if echo != data:
            raise UARTError(f"Echo mismatch: expected {data.hex(' ')}, received {echo.hex(' ')}")
        return deadline

    def loopback(self):
        with self.lock:
            self._send(bytes.fromhex("55 aa 12 34"))

    def read(self, register):
        with self.lock:
            deadline = self._send(read_request(register))
            reply = self._receive(8, deadline)
            if reply[:3] != bytes((0x05, 0xff, register)):
                raise UARTError(f"Invalid reply header/register: {reply.hex(' ')}")
            if crc8(reply[:-1]) != reply[-1]:
                raise UARTError(f"Invalid reply CRC: {reply.hex(' ')}")
            return int.from_bytes(reply[3:7], "big")

    def probe_write(self):
        """Rewrite unchanged GCONF and verify IFCNT; require disabled TMC220x."""
        with self.lock:
            inputs = self.read(IOIN)
            if inputs >> 24 != 0x20 or not inputs & (1 << 8):
                raise UARTError("IOIN does not identify a supported TMC220x (VERSION=0x20, SEL_A=1)")
            if not inputs & 1:
                raise UARTError("Driver is enabled (ENN=0); hold ENN high before the write test")
            value = self.read(GCONF)
            before = self.read(IFCNT) & 0xff
            self._send(_gconf_write(value))
            after = self.read(IFCNT) & 0xff
            if (after - before) & 0xff != 1:
                raise UARTError(f"Write not verified: IFCNT {before} -> {after}; expected +1 modulo 256")
            if self.read(GCONF) != value:
                raise UARTError("GCONF changed during the test (reset or another writer?)")
            return before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Verified UART device on GPIO14/15; no default mapping")
    parser.add_argument("--baud", type=int, choices=(19200, 115200), default=19200)
    parser.add_argument("--timeout", type=float, default=0.25, help="Transaction timeout in seconds")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print transmitted/received hex bytes")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("loopback", help="Verify TX -> RX only, no driver reply required")
    commands.add_parser("status", help="Read IOIN, GCONF, IFCNT and DRV_STATUS")
    commands.add_parser("probe-write", help="Rewrite unchanged GCONF, requiring ENN=1; verify IFCNT")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive and finite")
    try:
        import serial
    except ImportError:
        parser.exit(1, "Install UART support with: python -m pip install pyserial\n")
    def trace(direction, data):
        if args.verbose:
            print(f"{direction}: {data.hex(' ')}")
    try:
        with serial.Serial(args.port, args.baud, bytesize=serial.EIGHTBITS,
                           parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                           timeout=0.02, write_timeout=args.timeout,
                           xonxoff=False, rtscts=False, dsrdtr=False,
                           exclusive=True) as port:
            driver = TMC2208UART(port, args.timeout, trace)
            if args.command == "loopback":
                driver.loopback()
                print("TX/RX loopback OK (does not verify the path to the driver)")
            elif args.command == "status":
                for name, register in (("IOIN", IOIN), ("GCONF", GCONF), ("IFCNT", IFCNT), ("DRV_STATUS", 0x6f)):
                    value = driver.read(register)
                    print(f"{name}: 0x{value:08x}")
                    if register == IOIN:
                        print(f"  VERSION=0x{value >> 24:02x}, SEL_A={(value >> 8) & 1}, ENN={value & 1} (TMC220x)")
            else:
                before, after = driver.probe_write()
                print(f"Write verified: IFCNT {before} -> {after}; GCONF unchanged")
    except (UARTError, serial.SerialException, OSError) as exc:
        parser.exit(1, f"UART error: {exc}\n")


if __name__ == "__main__":
    main()
