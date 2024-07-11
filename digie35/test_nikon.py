#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-

from gpiozero.output_devices import *

import time
from rpi_hardware_pwm import HardwarePWM
import subprocess
import re

XPWR_PIN=27
GPIO_PWM = 12
FREQ = 30000
DUTY = 20   # 100 = 0 power,, 0 = 100% power
#GPIO_ = (26, 20, 19, 21)    Niki board
GPIO_ = (14, 20, 19, 21)
_STEPPER_MOTOR_PHASES = (0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001)
#_STEPPER_MOTOR_PHASES = (0b0001, 0b0010, 0b0100, 0b1000)

DELAY = 0.01

if XPWR_PIN > 0:
    xpwr_pin = OutputDevice(XPWR_PIN, initial_value=1, active_high=True)

out_pins = []
for pin in range(0, 4):
	out_pins.append(OutputDevice(GPIO_[pin], initial_value=0, active_high=True))

if GPIO_PWM != 0:
	pwm_pin = OutputDevice(GPIO_PWM, initial_value=1)
	params = ["pinctrl", "set", str(GPIO_PWM), "a0"]
	subprocess.call(params, shell=False)
	chip_no = 0
	proc = subprocess.run(['cat', '/sys/firmware/devicetree/base/model'], capture_output=True)
	if proc.stdout != None:
		proc.stdout = proc.stdout.decode("utf-8")
	if proc.stderr != None:
	    proc.stderr = proc.stderr.decode("utf-8")
	if proc.returncode == 0:
		if re.match("^Raspberry Pi 5", proc.stdout) != None:
			chip_no = 2
	#print("chipno: %s" % chip_no)
	pwm = HardwarePWM(pwm_channel=0, hz=150, chip=chip_no)
	pwm.start(0)
	pwm.change_frequency(FREQ)
	pwm.start(DUTY)

phase = 0
dir = 1
cnt = 0

try:
	while True:
		bits = _STEPPER_MOTOR_PHASES[phase]
		print(f"Phase: {bits:04b}, cnt: {cnt}         ", end="\r")
		for pin in range(0, 4):
			out_pins[pin].value = (bits & (1<<pin)) != 0
		time.sleep(DELAY)
		phase += dir
		if phase >= len(_STEPPER_MOTOR_PHASES):
			phase = 0
		elif phase < 0:
			phase = len(_STEPPER_MOTOR_PHASES)-1
		cnt += 1
except KeyboardInterrupt:
	print("\nCtrl+C aborting");
	for pin in range(0, 4):
		out_pins[pin].value = 0
	if GPIO_PWM != 0:
		pwm.stop()

