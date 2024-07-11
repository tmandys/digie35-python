#!/usr/bin/env python3
# vim: set expandtab:
# -*- coding: utf-8 -*-


# test in which position motor does not move when windings current is off
# makes sense for Allegro as TMC driver supports standstill reduction
from gpiozero.output_devices import *
import time

DRV_ALLEGRO=1
DRV_TMC=2

DRIVER=DRV_ALLEGRO

STEP_PIN = 12
DIR_PIN = 20
XPWR_PIN=27
if False:
	# v1.0
	MS0_PIN = 26
	MS1_PIN = 19
	ENABLE_PIN = -1
	RESET_PIN = 21
	PDN_UART_PIN = -1
else:
	# v1.1
	MS0_PIN = 19
	MS1_PIN = 15
	ENABLE_PIN = 21
	if DRIVER == DRV_TMC:
		RESET_PIN = -1
		PDN_UART_PIN = 14
	else:
		RESET_PIN = 14
		PDN_UART_PIN = -1


MICROSTEPPING = 1
DIR = 1   # 1 / -1
print(f"MS: {MICROSTEPPING}/{1<<MICROSTEPPING}, Dir: {DIR}")

if RESET_PIN > 0:
    reset_pin = OutputDevice(RESET_PIN, initial_value=0, active_high=True)
    reset_pin.value = 0
    time.sleep(0.5)
    reset_pin.value = 1

if PDN_UART_PIN > 0:
    pdn_uart_pin = OutputDevice(PDN_UART_PIN, initial_value=0, active_high=True)

if ENABLE_PIN > 0:
    enable_pin = OutputDevice(ENABLE_PIN, initial_value=0, active_high=True)

if DRIVER == DRV_TMC:
    # MS1 MS0 ... 00=1/8, 01=1/2, 10=1/4, 11=1/16
    ms0_pin = OutputDevice(MS0_PIN, initial_value = MICROSTEPPING in (0,3))
    ms1_pin = OutputDevice(MS1_PIN, initial_value = MICROSTEPPING in (1,3))
else:
    ms0_pin = OutputDevice(MS0_PIN, initial_value = (MICROSTEPPING & 1) != 0)
    ms1_pin = OutputDevice(MS1_PIN, initial_value = (MICROSTEPPING & 2) != 0)
    print(f"MS0_PIN: {MS0_PIN}->{(MICROSTEPPING & 1) !=0}")
    print(f"MS1_PIN: {MS1_PIN}->{(MICROSTEPPING & 2) !=0}")

if XPWR_PIN > 0:
    xpwr_pin = OutputDevice(XPWR_PIN, initial_value=1, active_high=True)

step_pin = OutputDevice(STEP_PIN, initial_value=0, active_high=True)
dir_pin = OutputDevice(DIR_PIN, initial_value= DIR > 0, active_high=True)

steps_per_full = 1 << MICROSTEPPING
PAUSE = 1
cnt = 0
try:
	while False:
		PAUSE = 0.00001
		print(f"Step-1, cnt: {cnt}         ", end="\r")
		step_pin.value = 1
		time.sleep(PAUSE)
		print(f"Step-0, cnt: {cnt}         ", end="\r")
		step_pin.value = 0
		time.sleep(PAUSE)
		cnt += 1

	while True:
		enable_pin.value = 0
		print(f"Position: {cnt}/{cnt % steps_per_full}/{steps_per_full}: ENABLE         ", end="\r");
		time.sleep(PAUSE)
		enable_pin.value = 1
		print(f"Position: {cnt}/{cnt % steps_per_full}/{steps_per_full}: DISABLE        ", end="\r");
		time.sleep(PAUSE)
		enable_pin.value = 0
		time.sleep(0.2)
		for i in (range(0, steps_per_full * 10 + 1)):
			print(f"Step: {cnt}/{cnt % steps_per_full}/{steps_per_full}                 ", end="\r");
			step_pin.value = 1
			time.sleep(0.01)
			step_pin.value = 0
			time.sleep(0.01)
			cnt += DIR
		time.sleep(PAUSE)

except KeyboardInterrupt:
	print("\nCtrl+C aborting");
	if ENABLE_PIN > 0:
		enable_pin.value = 1
	step_pin.value = 0
