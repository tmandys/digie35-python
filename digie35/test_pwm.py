#!/usr/bin/env python3

from rpi_hardware_pwm import HardwarePWM
import time

# RPI5 test fan on channel 3, rmmod pwm_fan
# GPIO12,13 does not work in kernel 6.1.63, works in 6.6.31

pwm = HardwarePWM(pwm_channel=1, hz=15000, chip=2)
pwm.start(100) # full duty cycle
time.sleep(1)
pwm.change_duty_cycle(50)
time.sleep(1)
pwm.change_duty_cycle(100)

pwm.stop()
