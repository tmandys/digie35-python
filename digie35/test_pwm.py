#!/usr/bin/env python3
# vim: set expandtab:
# -*- coding: utf-8 -*-

from rpi_hardware_pwm import HardwarePWM
import time
import subprocess
import re

# RPI5 test fan on channel 3, rmmod pwm_fan
# GPIO12,13 does not work in kernel 6.1.63, works in 6.6.31

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

pwm = HardwarePWM(pwm_channel=1, hz=15000, chip=chip_no)
pwm.start(100) # full duty cycle
time.sleep(1)
pwm.change_duty_cycle(50)
time.sleep(1)
pwm.change_duty_cycle(100)

pwm.stop()
