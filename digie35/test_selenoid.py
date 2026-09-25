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
PULSE = 0.5
XPWR_PIN = 27

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
        # bit-bang
        # IRLM open when Vgs>2.7V, time constant is 400ms, corresponds to 100ms  (10MF+47k)
        # so we can stop pulse, wait a moment and generate second pulse
        # measured on oscilloscope to keep Vdd near 0V as long time as possible.
        # TODO: use transistor with lower Vgson
        activate_pin.value = 1
        precise_sleep(0.09)
        activate_pin.value = 0
        precise_sleep(0.06)
        activate_pin.value = 1
        precise_sleep(0.04)
        activate_pin.value = 0
        precise_sleep(0.05)
        activate_pin.value = 1
        precise_sleep(0.04)
    else:
        activate_pin.value = 1
        time.sleep(PULSE)
    print(f"{slnd}, OFF,cnt: {cnt}         ", end="\r")
    activate_pin.value = 0
    time.sleep(PAUSE)

if XPWR_PIN > 1:
    xpwr_pin = OutputDevice(XPWR_PIN, initial_value=1, active_high=True)
PAUSE = 2
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

