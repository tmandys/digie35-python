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
__version__ = "0.2"

from digie35.digie35core import *
import subprocess
import logging
from smbus2 import SMBus as SMBus2, i2c_msg
from rpi_hardware_pwm import HardwarePWM
import time
import re
#import datetime

## @package digie35rpi
# Support for Digie35 via Raspberry Pi beyond GPIO


## Raspberry Pi 3/4/5 mainboard implementation
class RpiMainboard(Mainboard):
    _I2C_BUS = 1

    def __init__(self, use_i2c):
        super().__init__()
        if use_i2c:
            self._i2c_bus = SMBus2(self._I2C_BUS)

        self._pwm = {}
        self._i2c_lock = Lock()
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
        super().__del__()

    def set_gpio_function(self, num, func):
        super().set_gpio_function(num, func)


        if self._is_rpi5:
            params = ['pinctrl']
        else:
            params = ['raspi-gpio']
        params.append('set')
        params.append(str(num))
        if func == "i2c":
            if self._is_rpi5:
                params.append("a3")
            else:
                params.append("a0")
            #params.append("du")
        elif func  == "pwm":
            params.append("a0")
        elif func == "gpio":
            return
        else:
            DigitizerError("GPIO%d: Unknown function type '%s'" % (num, func))
        logging.getLogger().debug("exec: %s" % params)
        subprocess.call(params, shell=False)

    ## RPi4 PWM frequency supported at least to 5MHz
    def set_pwm(self, channel, duty_cycle, freq=None):
        duty_cycle2 = duty_cycle / 255 * 100
        logging.getLogger().debug("Set PWM(%d, %d, %s)", channel, duty_cycle2, freq)
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
            self._pwm[str(channel)].start(duty_cycle2)

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
