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
import RPi.GPIO as GPIO
import logging
from functools import partial
#import time
#import datetime

## @package digie35rpigpio
# Support for Digie35 via Raspberry Pi via RPi.GPIO library (which is not ported to RPI5)


## Raspberry Pi 3/4 mainboard GPIO implementation
class RpiGpioMainboard(RpiMainboard):

    def __init__(self, use_i2c):
        super().__init__(use_i2c)
        GPIO.setmode(GPIO.BCM)

        self._gpio_input_mask = 0
        self._gpio_output_mask = 0
        self._gpio_callback = partial(self._gpio_event_handler, self)
        self._callback_per_gpio = {}
        self._channel_to_name = {}

    def __del__(self):
        GPIO.cleanup()
        super().__del__()

    def set_gpio_as_input(self, num, pull_up_down):
        logging.getLogger().debug("GPIO as input: %s" % num)
        pud = GPIO.PUD_OFF
        if pull_up_down == True:
            pud = GPIO.PUD_UP
        elif pull_up_down == False:
            pud = GPIO.PUD_DOWN
        GPIO.setup(num, GPIO.IN, pull_up_down = pud)
        self._gpio_input_mask |= 1 << num
        self._gpio_output_mask &= ~ (1 << num)

    def set_gpio_event_handler(self, num, edge, name = None, handler = None):
        logging.getLogger().debug("GPIO event callback: %s(%s)" % (num, edge))
        if edge == "falling":
            edge = GPIO.FALLING
        elif edge == "raising":
            edge = GPIO.RISING
        elif edge == "both":
            edge = GPIO.BOTH
        elif edge == "none":
            GPIO.remove_event_detect(num)
            del self._channel_to_name[str(num)]
            return
        else:
            DigitizerError("Unknown edge type '%s'" % edge)
        logging.getLogger().debug("GPIO event callback: %s(%s)" % (num, edge))
        self._channel_to_name[str(num)] = name
        if handler != None:
            self._callback_per_gpio[str(num)] = handler
        GPIO.add_event_detect(num, edge, callback=self._gpio_callback)

    def set_gpio_as_output(self, num, init_hi):
        if init_hi == True:
            init = GPIO.HIGH
        else:
            init = GPIO.LOW
        logging.getLogger().debug("GPIO as output: %s, init: %s" % (num, init))
        GPIO.setup(num, GPIO.OUT, initial = init)
        self._gpio_output_mask |= 1 << num
        self._gpio_input_mask &= ~ (1 << num)

    def set_gpio(self, num, val):
        if self._gpio_output_mask & (1 << num) != 0:
            #logging.getLogger().debug("Set GPIO(%s): %d", num, val)
            GPIO.output(num, val != 0)

    def get_gpio(self, num):
        #logging.getLogger().debug("Get GPIO(%d)", num)
        return GPIO.input(num)

    def _gpio_event_handler(self, obj, channel):
        # in obj is <digie35board.RpiExtensionBoard object
        s = str(channel)
        logging.getLogger().debug("GPIO event(0x%x, %s)", channel, obj._channel_to_name[s])
        if s in obj._callback_per_gpio:
            logging.getLogger().debug("Override default handler")
            obj._callback_per_gpio[s](self, obj._channel_to_name[s])
        else:
            if self._xboard != None:
                self._xboard.on_gpio_change(obj._channel_to_name[s])
