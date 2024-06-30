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
from digie35.digie35rpi import *
from gpiozero.input_devices import *
from gpiozero.output_devices import *
import logging
from functools import partial
#import time
#import datetime

## @package digie35gpiozero
# Support for Digie35 via Raspberry Pi via GpioZero library (which is ported also to RPI 5)


## Raspberry Pi 3/4/5 mainboard GPIO implementation
class GpioZeroMainboard(RpiMainboard):

    def __init__(self, use_i2c):
        super().__init__(use_i2c)

        self._gpio_input_mask = 0
        self._gpio_output_mask = 0
        self._gpio_callback = partial(self._gpio_event_handler, self)
        self._callback_per_gpio = {}
        self._channel_to_name = {}
        self._ios = {}

    def __del__(self):
        super().__del__()

    def set_gpio_as_input(self, num, pull_up_down):
        logging.getLogger().debug("GPIO as input: %s" % num)
        num_s = str(num)
        if num_s in list(self._ios):
            del self._ios[num_s]
        self._ios[num_s] = Button(pin=num, pull_up=pull_up_down, active_state=True if pull_up_down == None else None)
        self._gpio_input_mask |= 1 << num
        self._gpio_output_mask &= ~ (1 << num)

    def set_gpio_event_handler(self, num, edge, name = None, handler = None):
        logging.getLogger().debug("GPIO event callback: %s(%s,%s)" % (num, edge, handler))
        if edge in ["falling", "raising", "both"]:
            pass
        elif edge == "none":
            self._ios[str(num)].when_pressed = None
            self._ios[str(num)].when_released = None
            del self._channel_to_name[str(num)]
            return
        else:
            DigitizerError("Unknown edge type '%s'" % edge)

        self._channel_to_name[str(num)] = name
        if handler != None:
            self._callback_per_gpio[str(num)] = handler
        if edge in ["falling", "both"]:
            self._ios[str(num)].when_released = self._gpio_callback
        if edge in ["raising", "both"]:
            self._ios[str(num)].when_pressed = self._gpio_callback

    def set_gpio_as_output(self, num, init):
        logging.getLogger().debug("GPIO as output: %s, init: %s" % (num, init))
        num_s = str(num)
        if num_s in list(self._ios):
            del self._ios[num_s]
        self._ios[num_s] = OutputDevice(pin=num, initial_value=init, active_high=True)
        self._gpio_output_mask |= 1 << num
        self._gpio_input_mask &= ~ (1 << num)

    def set_gpio(self, num, val):
        if self._gpio_output_mask & (1 << num) != 0:
            # logging.getLogger().debug("Set GPIO(%s): %d", num, val)
            self._ios[str(num)].value = val

    def get_gpio(self, num):
        # logging.getLogger().debug("Get GPIO(%d)", num)
        return self._ios[str(num)].value

    def _gpio_event_handler(self, self2, device):
        # in obj is <digie35board.RpiExtensionBoard object
        # logging.getLogger().debug("GPIO event(%s, %s, %s)", self, self2, device)
        channel = device.pin.number
        s = str(channel)
        logging.getLogger().debug("GPIO event(0x%x, %s)", channel, self._channel_to_name[s])
        if s in self._callback_per_gpio:
            logging.getLogger().debug("Override default handler")
            self._callback_per_gpio[s](self, self._channel_to_name[s])
        else:
            if self._xboard != None:
                self._xboard.on_gpio_change(self._channel_to_name[s])
