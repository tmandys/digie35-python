#!/usr/bin/env python3

import RPi.GPIO as GPIO
import time
from rpi_hardware_pwm import HardwarePWM
import subprocess

GPIO_PWM = 12
FREQ = 30000
DUTY = 20   # 100 = 0 power,, 0 = 100% power
#GPIO_ = (26, 20, 19, 21)
GPIO_ = (14, 20, 19, 21)
_STEPPER_MOTOR_PHASES = (0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001)
#_STEPPER_MOTOR_PHASES = (0b0001, 0b0010, 0b0100, 0b1000)

DELAY = 0.001

GPIO.setmode(GPIO.BCM)
for pin in range(0, 4):
    GPIO.setup(GPIO_[pin], GPIO.OUT, initial = 0)

if GPIO_PWM != 0:
	GPIO.setup(GPIO_PWM, GPIO.OUT, initial = 1)
	params = ["raspi-gpio", "set", str(GPIO_PWM), "a0"]
	subprocess.call(params, shell=False)
	pwm = HardwarePWM(pwm_channel=0, hz=150)
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
			GPIO.output(GPIO_[pin], (bits & (1<<pin)) != 0)
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
		GPIO.output(GPIO_[pin], 0)
	if GPIO_PWM != 0:
		pwm.stop()

