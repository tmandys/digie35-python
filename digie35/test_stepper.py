#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-

from gpiozero.output_devices import *

import time
VERSION=103

DRV_ALLEGRO=1
DRV_TMC=2

DRIVER=DRV_TMC

STEP_PIN = 12
DIR_PIN = 20
XPWR_PIN = 27
if VERSION==100:
    # v1.0
    MS0_PIN = 26
    MS1_PIN = 19
    ENABLE_PIN = -1
    RESET_PIN = 21
    PDN_UART_PIN = -1
else:
    # v1.1
    MS0_PIN = 19   # XIO4
    MS1_PIN = 15   # XIO5
    ENABLE_PIN = 21
    if DRIVER == DRV_TMC:
        RESET_PIN = -1
        PDN_UART_PIN = 14
    else:
        RESET_PIN = 14
        PDN_UART_PIN = -1
    if VERSION >= 103:
        enable_active = 1
    else:
        enable_active = 0

MICROSTEPPING = 3
DIR = 1

if DRIVER == DRV_TMC and MICROSTEPPING == 0:
    # TMC has no full steps in legacy mode ?
    MICROSTEPPING = 1
 
if RESET_PIN > 0:
    reset_pin = OutputDevice(RESET_PIN, initial_value=0, active_high=True)
    reset_pin.value = 0
    time.sleep(0.5)
    reset_pin.value = 1

if PDN_UART_PIN > 0:
    pdn_uart_pin = OutputDevice(PDN_UART_PIN, initial_value=0, active_high=True)

if ENABLE_PIN > 0:
    enable_pin = OutputDevice(ENABLE_PIN, initial_value=enable_active, active_high=True)

if DRIVER == DRV_TMC:
    # MS1 MS0 (datasheet MS2, MS1) ... 00=1/8, 01=1/2, 10=1/4, 11=1/16
    ms0_pin = OutputDevice(MS0_PIN, initial_value = MICROSTEPPING in (1,4))
    ms1_pin = OutputDevice(MS1_PIN, initial_value = MICROSTEPPING in (2,4))
else:
    ms0_pin = OutputDevice(MS0_PIN, initial_value = (MICROSTEPPING & 1) != 0)
    ms1_pin = OutputDevice(MS1_PIN, initial_value = (MICROSTEPPING & 2) != 0)

if XPWR_PIN > 0:
    xpwr_pin = OutputDevice(XPWR_PIN, initial_value=1, active_high=True)

step_pin = OutputDevice(STEP_PIN, initial_value=0, active_high=True)
dir_pin = OutputDevice(DIR_PIN, initial_value= DIR > 0, active_high=True)

PAUSE = 0.00001
cnt = 0
try:
    while True:
        print(f"Step-1, cnt: {cnt}         ", end="\r")
        step_pin.value = 1
        time.sleep(PAUSE)
        print(f"Step-0, cnt: {cnt}         ", end="\r")
        step_pin.value = 0
        time.sleep(PAUSE)
        cnt += 1

except KeyboardInterrupt:
    print("\nCtrl+C aborting");
    step_pin.value = 0
    if ENABLE_PIN > 0:
        enable_pin.value = enable_active ^ 1

