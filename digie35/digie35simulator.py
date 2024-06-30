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

from threading import Thread
#from datetime import timedelta, datetime
import logging
from digie35.digie35core import Mainboard, DigitizerError

## @package digie35simulator
# Simulator mainboard for Digie35

## For debugging/development purpose
class SimulatorMainboard(Mainboard):
    def __init__(self):
        super().__init__()
        self._xio_value = 0
        self._xio_input_mask = 0
        self._gpio = {}
        self._eeprom = {}
        self._eeprom_page_size = 8
        for key in ["xboard", "adapter", "light", ]:
            self._eeprom[key] = []
            for i in range(0, 2048//8):
                self._eeprom[key].append(0xFF)
            self._eeprom[key][32] = 0 # version
            self._eeprom[key][33] = 0

    def debug(self, name, **kwargs):
        if name == "set_xio_input":
            self._xio_input_mask = kwargs["input_mask"]
            self._xio_value = kwargs["value"] & self._xio_input_mask | self._xio_value & ~self._xio_input_mask
            #logging.getLogger().debug("set PCF inputs: 0x%x 0x%x -> 0x%x" % (kwargs["value"], self._xio_input_mask, self._xio_value))

    def set_gpio_as_input(self, num, pull_up_down, callback = None):
        item = {
            "num": num,
            "in_out": True,
            "val": 1 if pull_up_down == "up" else 0,
            "callback": callback,
        }
        logging.getLogger().debug("set_gpio_as_input: %s" % item)
        self._gpio[str(num)] = item

    def set_gpio_as_output(self, num, init_hi):
        item = {
            "num": num,
            "in_out": False,
            "val": 1 if init_hi else 0,
        }
        logging.getLogger().debug("set_gpio_as_output: %s" % item)
        self._gpio[str(num)] = item

    def set_gpio_event_handler(self, num, edge, name = None, handler = None):
        if not str(num) in self._gpio:
            raise DigitizerError("GPIO %s error" % num)
        if edge == "":
            del self._gpio[str(num)]["edge"]
        else:
            self._gpio[str(num)]["edge"] = edge
            self._gpio[str(num)]["handler"] = handler
            self._gpio[str(num)]["name"] = name

    def set_gpio(self, num, val):
        if str(num) in self._gpio:
            item = self._gpio[str(num)]
            if item["val"] != val:
                prev_val = self._gpio[str(num)]["val"]
                self._gpio[str(num)]["val"] = val
                if "edge" in item:
                    if  (item["edge"] == "falling" and prev_val != 0 and val == 0) or (item["edge"] == "raising" and prev_val == 0 and val != 0) or (item["edge"] == "both"):
                        self._start_sensor_thread(item)
        else:
            raise DigitizerError("GPIO %s error" % num)

    def get_gpio(self, num):
        if str(num) in self._gpio:
            return self._gpio[str(num)]["val"]
        raise DigitizerError("GPIO %s error" % num)

    def set_pwm(self, channel, duty_cycle, freq=None):
        pass

    def i2c_write_read(self, i2c_addr, out_data, in_count):
        if i2c_addr == 0x54:
            eeprom = "xboard"

        elif i2c_addr == 0x55:
            eeprom = "adapter"

        elif i2c_addr == 0x56:
            eeprom = "light"

        elif i2c_addr == 0b0100011:
            if in_count > 0:
                return [self._xio_value]
            if len(out_data) > 0:
                self._xio_value = out_data[0] & ~self._xio_input_mask | self._xio_value & self._xio_input_mask
                #logging.getLogger().debug("set PCF outputs: 0x%x 0x%x -> 0x%x" % (out_data[0], self._xio_input_mask, self._xio_value))
                return
            return
        else:
            raise DigitizerError("I2C I/O error 0x%x" % i2c_addr)
        addr = out_data[0]
        if in_count > 0:
            result = []
            while in_count > 0:
                result.append(self._eeprom[eeprom][addr % len(self._eeprom[eeprom])])
                addr += 1
                in_count -= 1
            return result
        else:
            i = 1
            page_addr = addr & ~(self._eeprom_page_size - 1)
            while i < len(out_data):
                self._eeprom[eeprom][page_addr + addr % self._eeprom_page_size] = out_data[i]
            return

    def _start_sensor_thread(self, item):
        # start in new thread
        if hasattr(self, "_sensor_thread"):
            self._sensor_thread.join()
        logging.getLogger().debug("start sensor change thread %s" % (item))
        if item["handler"] != None:   # TODO: how to do it with parameter passing?
            # kwargs rather then args=("string", ) where is trick to: provide tuple not to split string as arguments, i.e. args=("string")
            self._sensor_thread = Thread(target = item["handler"], kwargs = {"source": item["name"]})
            self._sensor_thread.name = "simulator_sensor"
            self._sensor_thread.start()
        else:
            if self._xboard != None:
                self._sensor_thread = Thread(target=self._xboard.on_gpio_change, kwargs={"source": item["name"]})
                self._sensor_thread.name = "simulator_sensor"
                self._sensor_thread.start()
