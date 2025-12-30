#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-

from gpiozero.output_devices import *

import time
VERSION=106

X_PWM = 12
X_IO1 = 21
X_IO2 = 20

ENABLE = X_IO1
SELECT = X_IO2
ACTIVATE = X_PWM
PWM_FREQ = 14000
RATIO = 0.8

enable_pin = OutputDevice(X_IO1, initial_value=0, active_high=False)
select_pin = OutputDevice(X_IO2, initial_value=0, active_high=True)
activate_pin = OutputDevice(X_PWM, initial_value=0, active_high=True)

def precise_sleep(sec):
    target = time.perf_counter_ns() + sec*1e+9
    while target > time.perf_counter_ns():
        pass
def push_selenoid(slnd):
    print(f"{slnd}, ON ,cnt: {cnt}         ", end="\r")
    if VERSION >= 106:
        ts = time.perf_counter()
        # bit-bang PWM
        while time.perf_counter() - ts <= PULSE:
            activate_pin.value = 1
            precise_sleep(1/PWM_FREQ*RATIO)
            if RATIO < 1.0:
                activate_pin.value = 0
                precise_sleep(1/PWM_FREQ*(1-RATIO))
    else:
        activate_pin.value = 1
        time.sleep(PULSE)
    print(f"{slnd}, OFF,cnt: {cnt}         ", end="\r")
    activate_pin.value = 0
    time.sleep(PAUSE)

PAUSE = 2
PULSE = 0.1
cnt = 0
try:
    activate_pin.value = 0
    enable_pin.value = 1
    while True:
        select_pin.value = 1
        push_selenoid("Down")
        select_pin.value = 0
        push_selenoid("Up")
        cnt += 1

except KeyboardInterrupt:
    print("\nCtrl+C aborting");
    activate_pin.value = 0
    enable_pin.value = 0

