# TMC2208 UART diagnostics (first implementation stage)

This standalone tool checks the UART wiring before integrating driver configuration
into FilmDigitizer35. It does not move the motor, change the current, set microsteps,
drive GPIO or program OTP. The only write command rewrites the existing GCONF value.

## Prepare the hardware

Keep the motor disabled through EN throughout the test. The tool can check the
driver's ENN input before its write test, but cannot hold the physical pin high.
Stop the Digie35 application and any other program controlling these pins first.
Existing adapter definitions use `in_out_3` as `stepper_sleep` and `in_out_5` as
`stepper_ms1`; running them alongside UART diagnostics can interfere with UART.

Verify a hardware UART actually routes TX/RX to GPIO14/15 (physical pins 8/10),
enable that UART and disable its serial login console. The tool requires an explicit
`--port`; it does not assume a common device name across RPi 3/4/5. In particular,
do not assume `/dev/serial0` refers to those header pins on every model.

The proposed adapter wiring from the hardware investigation is:

- VCC_IO 3.3 V and common ground.
- TX and RX each through the verified 1 kOhm resistor path to PDN_UART.
- JP505 1-2, module jumper routing PDN_UART to the A4988-labelled RST position.
- JP506 2-3, disconnecting RX from MS2 and joining it to TX; JP507 open.

These connections still require confirmation against the actual module and
populated adapter. A successful TX/RX loopback does not confirm JP505 or the
module's internal jumper. UART does not resolve the separate VMOT capacitor issue.

## Install and run

In the Python environment used for the project:

```sh
python -m pip install 'pyserial>=3.5'
```

Installing the project package (`python -m pip install .` from the repository
root) installs pyserial automatically as a required dependency.

Replace `/dev/YOUR_UART` below with the device verified on your Raspberry Pi.
The default is 19200 baud, 8N1. `-v` prints actual TX/RX bytes; RX lines may show
partial chunks. Run these commands in order:

```sh
python -m digie35.tmc2208_uart --port /dev/YOUR_UART -v loopback
python -m digie35.tmc2208_uart --port /dev/YOUR_UART -v status
python -m digie35.tmc2208_uart --port /dev/YOUR_UART -v probe-write
```

After package installation, `digie35_tmc2208` is an equivalent entry point.

1. `loopback` sends `55 aa 12 34` in one write and requires the same bytes back.
   This works without the driver and checks only the TX-to-RX path.
2. `status` reads IOIN, GCONF, IFCNT and DRV_STATUS. Each transaction requires its
   echo followed by a separate valid reply. Missing echo, bad CRC, wrong register
   and timeout are errors, not successful zero-valued reads.
3. `probe-write` requires compatible IOIN identification and ENN=1. It rewrites
   unchanged GCONF, checks IFCNT increased by one modulo 256, and reads GCONF back.
   It never automatically retries a write whose result is uncertain.

Use `--baud 115200` only after the initial connection works. An error exits with
status 1 and includes diagnostic details. The port is opened exclusively on Linux;
this does not prevent unrelated software from reconfiguring GPIO.

## Tests without RPi

```sh
python -m unittest discover -s tests -p test_tmc2208_uart.py
```

The serial device is simulated. Tests cover framing/CRC, fragmented input, stale
buffer contents, missing/corrupt replies, partial writes, ENN checks and IFCNT
wraparound. CRC is checked against a separate reflected-table implementation of
the ADI algorithm, including fixed read datagrams. These are not hardware tests.

## Application UART transport

`RpiMainboard.uart_write_read(out_data, in_count)` now opens the serial port lazily,
sends binary data in one write, and returns exactly `in_count` bytes (or raises
`DigitizerError`). The TX entry's `echo` property controls whether the transmitted
bytes must be received and checked before the reply, including write-only calls.
CRC, response headers and IFCNT remain the adapter's responsibility.

Defaults in `digie35/digie35rpi.py` are `_UART_DEVICE = "/dev/ttyAMA0"`,
`_UART_BAUDRATE = 19200`, and `_UART_TIMEOUT = 0.25` seconds. This explicitly targets
PL011 UART0, not mini-UART. Verify the device on the actual Pi before running the
application; change `_UART_DEVICE` if that verified UART has a different name.
The selected pin functions are ALT0 on Pi 3/4 and ALT4 on Pi 5, GPIO14/15 only.

Pin function selection alone does not enable the Linux UART device. Configure
Raspberry Pi OS and reboot first. Typical configurations in `/boot/firmware/config.txt`
(`/boot/config.txt` on older images) are:

- Pi 3/4: `enable_uart=1` and `dtoverlay=disable-bt` to free PL011 for GPIO14/15.
  This disables onboard Bluetooth; also disable the `hciuart` service. If Bluetooth
  is required, investigate the `miniuart-bt` overlay instead.
- Pi 5: `dtoverlay=uart0-pi5` enables UART0 on GPIO14/15. The dedicated debug UART
  is a different peripheral, and `/dev/serial0` may refer to it.

Disable the serial login console (for example via `raspi-config`) and ensure the
selected port is not used by a `console=...` kernel argument or serial getty.
The application user needs access to the device, normally through the `dialout`
group. The application does not edit OS configuration or services automatically.
Run the standalone loopback/status tests above on the verified port before enabling
the UART adapter. Pyserial is installed automatically with the project package.

Transport calls are serialized, have finite read/write timeouts, and are never
automatically retried. A short idle gap and input buffer reset precede each request;
this API is for synchronous request/reply devices, not unsolicited serial streams.
The lock covers one exchange, not a multi-exchange register read/modify/write.
Adapter operations must serialize such sequences separately.

Run transport and adapter tests without Raspberry Pi hardware:

```sh
python -m unittest tests.test_rpi_uart tests.test_tmc_current tests.test_tmc_registers tests.test_solenoid_index tests.test_tmc2208_uart
```

OS setup references: [Raspberry Pi UART documentation](https://www.raspberrypi.com/documentation/computers/configuration.html),
[official overlay definitions](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README).

## Hardware verification still required

Before using software current configuration, confirm actual Rsense and
whether the motor's stated 0.7 A is RMS or peak. No current is inferred here.
Integration must hold EN disabled until configuration is verified, retain STEP/DIR
motion, preserve step calibration, and restore configuration after driver reset.
The standalone diagnostic tool does not configure current or implement reset recovery.

References:

- [TMC2208 datasheet, sections 4 and 5](https://www.analog.com/media/en/technical-documentation/data-sheets/TMC2202_TMC2208_TMC2224_datasheet_rev1.14.pdf)
- [Analog Devices reference UART/CRC implementation](https://github.com/analogdevicesinc/TMC-API/blob/master/tmc/ic/TMC2208/TMC2208.c)
