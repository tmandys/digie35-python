# vim: set expandtab:
# -*- coding: utf-8 -*-
#
# Copyright (c) 2023 MandySoft
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

__author__ = "Tomas Mandys"
__copyright__ = "Copyright (C) 2023 MandySoft"
__licence__ = "MIT"
__version__ = "0.3"

from digie35.digie35core import *
import subprocess
import logging
from smbus2 import SMBus as SMBus2, i2c_msg
from rpi_hardware_pwm import HardwarePWM
import time
import re
from evdev import InputDevice, categorize, ecodes, list_devices
#import datetime

## @package digie35rpi
# Support for Digie35 via Raspberry Pi beyond GPIO


## Raspberry Pi 3/4/5 mainboard implementation
class RpiMainboard(Mainboard):
    _I2C_BUS = 1
    # PL011 UART0 on GPIO14/15; requires the corresponding OS overlay.
    # Do not use serial0 blindly: on Pi 5 it may point at the debug connector.
    _UART_DEVICE = "/dev/ttyAMA0"
    _UART_BAUDRATE = 19200
    _UART_TIMEOUT = 0.25

    def __init__(self, use_i2c):
        super().__init__()
        if use_i2c:
            self._i2c_bus = SMBus2(self._I2C_BUS)

        self._pwm = {}
        self._input_devices = {}
        self._i2c_lock = Lock()
        self._uart_lock = Lock()
        self._uart = None
        self._is_rpi5 = False
        proc = subprocess.run(['cat', '/sys/firmware/devicetree/base/model'], capture_output=True)
        logging.getLogger().debug("Response: %s" % (proc))
        if proc.stdout != None:
            proc.stdout = proc.stdout.decode("utf-8")
        if proc.stderr != None:
            proc.stderr = proc.stderr.decode("utf-8")
        if proc.returncode == 0:
            self._is_rpi5 = re.match("^Raspberry Pi 5", proc.stdout) != None
            logging.getLogger().debug("RPI5: %s", self._is_rpi5)

    def __del__(self):
        if getattr(self, "_uart", None) is not None:
            self._uart.close()
        super().__del__()
        if not self._is_rpi5:
            # RPI4: GPIO20,21 have voltage in ipput state between 1.6-1.8V depending on internal pullup/down which enables stepper @IO1 so force 0V
            params = ['raspi-gpio', 'set', '21', 'op', 'dl']
            logging.getLogger().debug("exec: %s" % params)
            subprocess.call(params, shell=False)

    def is_rpi5(self):
        return self._is_rpi5

    def set_gpio_function(self, num, func):
        super().set_gpio_function(num, func)


        if self._is_rpi5:
            params = ['pinctrl']
        else:
            params = ['raspi-gpio']
        params.append('set')
        params.append(str(num))
        match func:
            case "i2c":
                if self._is_rpi5:
                    params.append("a3")
                else:
                    params.append("a0")
                #params.append("du")
            case "pwm":
                params.append("a0")
            case "gpio":
                return
            case "uart":
                if num not in (14, 15):
                    raise ValueError(f"GPIO{num}: Unsupported UART pin")
                params.append("a4" if self._is_rpi5 else "a0")
            case _:
                raise ValueError(f"GPIO{num}: Unknown function type '{func}'")
        logging.getLogger().debug("exec: %s" % params)
        if func == "uart":
            subprocess.run(params, check=True)
        else:
            subprocess.call(params, shell=False)

    ## RPi4 PWM frequency supported at least to 5MHz, duty cycle is 0-1
    def set_pwm(self, channel, duty_cycle, freq=None):
        logging.getLogger().debug(f"Set PWM({channel}, {duty_cycle}, {freq})")
        if duty_cycle == 0:
            if str(channel) in self._pwm:
                self._pwm[str(channel)].stop()
                del self._pwm[str(channel)]
        else:
            if not str(channel) in self._pwm:
                if freq == None:
                    freq = 15555
                if self._is_rpi5:
                    chip_no = 2
                else:
                    chip_no = 0
                logging.getLogger().debug("HardwarePWM(%d, %d, %s)", channel, freq, chip_no)
                self._pwm[str(channel)] = HardwarePWM(pwm_channel=channel, hz=freq, chip=chip_no)
            self._pwm[str(channel)].start(duty_cycle * 100)

    def i2c_write_read(self, i2c_addr, out_data, in_count):
        # logging.getLogger().debug("%s(0x%x, %s, %s)" % (__name__, i2c_addr, out_data, in_count))
        self._i2c_lock.acquire()
        try:
            if out_data != None and len(out_data) > 0:
                write = i2c_msg.write(i2c_addr, out_data)
            else:
                write = None
            if in_count > 0:
                read = i2c_msg.read(i2c_addr, in_count)
            else:
                read = None

            result = None
            if read != None and write != None:
                self._i2c_bus.i2c_rdwr(write, read) # combined read&write
                result = list(read)
            elif read != None:
                self._i2c_bus.i2c_rdwr(read)
                result = list(read)
            elif write != None:
                self._i2c_bus.i2c_rdwr(write)
        finally:
            self._i2c_lock.release()
        return result

    def uart_write_read(self, out_data, in_count):
        """Send one binary request, consume optional wiring echo, return reply bytes.

        One lock covers the entire transaction. No retries: a failed transaction
        may already have changed the peripheral. Protocol validation is the caller's job.
        """
        data = bytes(out_data) if out_data is not None else b""
        if not isinstance(in_count, int) or in_count < 0:
            raise ValueError("UART receive count must be a non-negative integer")
        with self._uart_lock:
            tx = [item for item in self._xboard._io_map.values()
                  if item["type"] == "uart" and item["dir"] == "o"]
            if len(tx) != 1:
                raise DigitizerError("UART requires one TX entry in the IO map")
            echo = tx[0].get("echo", False)
            try:
                import serial
            except ImportError as exc:
                raise DigitizerError("UART requires pyserial: python -m pip install 'pyserial>=3.5'") from exc
            try:
                if self._uart is None:
                    self._uart = serial.Serial(
                        self._UART_DEVICE, self._UART_BAUDRATE,
                        bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE, timeout=self._UART_TIMEOUT,
                        write_timeout=self._UART_TIMEOUT, xonxoff=False,
                        rtscts=False, dsrdtr=False, exclusive=True,
                    )
                port = self._uart
                # Idle guard also lets an old/incomplete half-duplex transfer expire.
                time.sleep(320 / self._UART_BAUDRATE)
                port.reset_input_buffer()
                deadline = time.monotonic() + self._UART_TIMEOUT
                if data and port.write(data) != len(data):
                    raise DigitizerError("UART incomplete write (not retried)")

                def receive(count):
                    result = bytearray()
                    while len(result) < count:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise DigitizerError(f"UART timeout: received {len(result)}/{count} bytes")
                        port.timeout = remaining
                        result.extend(port.read(count - len(result)))
                    return bytes(result)

                if echo and receive(len(data)) != data:
                    raise DigitizerError("UART echo does not match transmitted data")
                reply = receive(in_count)
                # Without echo/reply, write() only confirms queuing to the OS.
                # Wait for TX with a deadline instead of potentially unbounded flush().
                while port.out_waiting:
                    if time.monotonic() >= deadline:
                        raise DigitizerError("UART transmit timeout")
                    time.sleep(0.001)
                if data and not echo and not in_count:
                    time.sleep(10 / self._UART_BAUDRATE)  # final 8N1 character
                return reply
            except (serial.SerialException, OSError, DigitizerError) as exc:
                # Drop any still-queued bytes; next call starts with a fresh port.
                if self._uart is not None:
                    for cleanup in (self._uart.reset_output_buffer, self._uart.close):
                        try:
                            cleanup()
                        except (serial.SerialException, OSError):
                            pass
                    self._uart = None
                raise DigitizerError(f"UART {self._UART_DEVICE}: {exc}") from exc

    def close_uart(self):
        with self._uart_lock:
            if self._uart is not None:
                self._uart.close()
                self._uart = None

    def set_input_device(self, id_name):
        if id_name in self._input_devices:
            return
        devices = [InputDevice(path) for path in list_devices()]
        for device in devices:
            if id_name in device.name:
                logging.getLogger().debug(f"Input device '%s' found '%s'" % (device.name, device.path))
                self._input_devices[id_name] = {
                    "device": device,
                    "keys": {},
                    "thread": None,
                }
                return
        raise DigitizerError(f"Input device '{id_name}' not found")

    def get_input_device_state(self, id_name, num):
        if not id_name in self._input_devices:
            raise DigitizerError(f"Input device '{id_name}' is not registered")
        logging.getLogger().debug(f"get_input_device_state(%s, %s): device: %s, keys: %s" % (id_name, num, self._input_devices[id_name]["device"], self._input_devices[id_name]["device"].active_keys()))
        return ecodes.ecodes[num] in self._input_devices[id_name]["device"].active_keys()

    def set_input_device_handler(self, id_name, num, edge, name = None, handler = None):
        if not id_name in self._input_devices:
            raise DigitizerError(f"Input device '{id_name}' is not registered")
        if edge == "none":
            if num in self._input_devices[id_name]["keys"]:
                del self._input_devices[id_name]["keys"][num]
            if not self._input_devices[id_name]["keys"]:
                self._input_devices[id_name]["thread"].join()
                self._input_devices[id_name]["thread"] = None
        else:
            self._input_devices[id_name]["keys"][num] = {
                "name": name,
                "edge": edge,
                "handler": handler,
            }
            if self._input_devices[id_name]["thread"] == None:
                self._input_devices[id_name]["thread"] = Thread(target=self._input_device_handler, kwargs={"id_name": id_name})
                self._input_devices[id_name]["thread"].name = "input_device:" + id_name
                self._input_devices[id_name]["thread"].start()

    def _input_device_handler(self, id_name):
        logging.getLogger().debug(f"_input_device_handler(%s): started" % (id_name))
        device = self._input_devices[id_name]["device"]
        for event in device.read_loop():
            if not self._input_devices[id_name]["keys"]:
                break
            if not self._xboard._initialized:
                continue
            logging.getLogger().debug(f"_input_device_handler(%s): event: %s" % (id_name, event))
            if event.type == ecodes.EV_KEY:
                key_event = categorize(event)
                logging.getLogger().debug(f"EventId: %s, Key_event: code: %s, state: %s" % (id_name, key_event.keycode, key_event.keystate))
                if key_event.keycode in list(self._input_devices[id_name]["keys"]):
                    item = self._input_devices[id_name]["keys"][key_event.keycode]
                    if (key_event.keystate == 1 and item["edge"] in ["raising", "both"]) or \
                        (key_event.keystate == 0 and item["edge"] in ["falling", "both"]):
                        if item["handler"] != None:
                            item["handler"](item["name"])
                        else:
                            self._xboard.on_gpio_change(item["name"])
        logging.getLogger().debug(f"_input_device_handler(%s): terminating" % (id_name))
