#!/usr/bin/env python3

# test in which position motor does not move when windings current is off
# makes sense for Allegro as TMC driver supports standstill reduction
import RPi.GPIO as GPIO
import time

DRV_ALLEGRO=1
DRV_TMC=2

DRIVER=DRV_ALLEGRO

STEP_PIN = 12
DIR_PIN = 20
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

GPIO.setmode(GPIO.BCM)

if RESET_PIN > 0:
	GPIO.setup(RESET_PIN, GPIO.OUT)
	GPIO.output(RESET_PIN, 0)
	time.sleep(0.5)
	GPIO.output(RESET_PIN, 1)

if PDN_UART_PIN > 0:
	GPIO.setup(PDN_UART_PIN, GPIO.OUT)
	GPIO.output(PDN_UART_PIN, 0)

if ENABLE_PIN > 0:
	GPIO.setup(ENABLE_PIN, GPIO.OUT)
	GPIO.output(ENABLE_PIN, 0)

if DRIVER == DRV_TMC:
	# MS1 MS0 ... 00=1/8, 01=1/2, 10=1/4, 11=1/16
	GPIO.setup(MS0_PIN, GPIO.OUT, initial = MICROSTEPPING in (0,3))
	GPIO.setup(MS1_PIN, GPIO.OUT, initial = MICROSTEPPING in (1,3))
else:
	GPIO.setup(MS0_PIN, GPIO.OUT, initial = (MICROSTEPPING & 1) !=0)
	GPIO.setup(MS1_PIN, GPIO.OUT, initial = (MICROSTEPPING & 2) !=0)
	print(f"MS0_PIN: {MS0_PIN}->{(MICROSTEPPING & 1) !=0}")
	print(f"MS1_PIN: {MS1_PIN}->{(MICROSTEPPING & 2) !=0}")

GPIO.setup(STEP_PIN, GPIO.OUT, initial = 0)
GPIO.setup(DIR_PIN, GPIO.OUT, initial = DIR > 0)

steps_per_full = 1 << MICROSTEPPING
PAUSE = 1
cnt = 0
try:
	while False:
		PAUSE = 0.00001
		print(f"Step-1, cnt: {cnt}         ", end="\r")
		GPIO.output(STEP_PIN, 1)
		time.sleep(PAUSE)
		print(f"Step-0, cnt: {cnt}         ", end="\r")
		GPIO.output(STEP_PIN, 0)
		time.sleep(PAUSE)
		cnt += 1

	while True:
		GPIO.output(ENABLE_PIN, 0)
		print(f"Position: {cnt}/{cnt % steps_per_full}/{steps_per_full}: ENABLE         ", end="\r");
		time.sleep(PAUSE)
		GPIO.output(ENABLE_PIN, 1)
		print(f"Position: {cnt}/{cnt % steps_per_full}/{steps_per_full}: DISABLE        ", end="\r");
		time.sleep(PAUSE)
		GPIO.output(ENABLE_PIN, 0)
		time.sleep(0.2)
		for i in (range(0, steps_per_full * 10 + 1)):
			print(f"Step: {cnt}/{cnt % steps_per_full}/{steps_per_full}                 ", end="\r");
			GPIO.output(STEP_PIN, 1)
			time.sleep(0.01)
			GPIO.output(STEP_PIN, 0)
			time.sleep(0.01)
			cnt += DIR
		time.sleep(PAUSE)

except KeyboardInterrupt:
	print("\nCtrl+C aborting");
	if ENABLE_PIN > 0:
		GPIO.output(ENABLE_PIN, 1)
	GPIO.output(STEP_PIN, 0)
