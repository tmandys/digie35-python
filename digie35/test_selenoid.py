#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-

from gpiozero.output_devices import *

import time
VERSION=104

X_PWM = 12
X_IO1 = 21
X_IO2 = 20

ENABLE = X_IO1
SELECT = X_IO2
ACTIVATE = X_PWM

enable_pin = OutputDevice(X_IO1, initial_value=0, active_high=False)
select_pin = OutputDevice(X_IO2, initial_value=0, active_high=True)
activate_pin = OutputDevice(X_PWM, initial_value=0, active_high=True)



PAUSE = 2
PULSE = 0.1
cnt = 0
try:
    activate_pin.value = 0
    enable_pin.value = 1
    while True:
        print(f"Down, cnt: {cnt}         ", end="\r")
        select_pin.value = 1
        activate_pin.value = 1
        time.sleep(PULSE)
        activate_pin.value = 0
        time.sleep(PAUSE)
        print(f"Up, cnt: {cnt}         ", end="\r")
        select_pin.value = 0
        activate_pin.value = 1
        time.sleep(PULSE)
        activate_pin.value = 0
        time.sleep(PAUSE)
        cnt += 1

except KeyboardInterrupt:
    print("\nCtrl+C aborting");
    activate_pin.value = 0
    enable_pin.value = enable_pin.active ^ 1

