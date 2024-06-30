#!/usr/bin/env python3

import digie35board
import digie35rpi

from smbus2 import SMBus as SMBus2

bus_id = 1

mainboard = digie35rpi.RpiMainboard(True)
xboard = digie35board.GulpExtensionBoard(mainboard, None)
eeprom = xboard._xboard_memory

h = {}
eeprom.write_header(h)

h = eeprom.read_header()
print("%s" % h)
h = eeprom.read_custom()
print("%s" % h)
exit()

eeprom = digie35board.RpiBoardEeprom(smbus, 0x54)

val = 0x89ABCDEF
for i in range(1, 5):
    addr = (i-1)*4
    eeprom.write_number(addr, val, i)
    val2 = eeprom.read_number(addr, i)
    exp_val = val & ((1<<(8*i))-1)
    if val2 != exp_val:
        print("ERROR: write/read_number addr: %s, expected: %s, got: %s" % (addr, exp_val, val2))

val = []
for i in range(0, 21):
    val.append(100+i)

addr = 25
eeprom.write_array(addr, val)
val2 = eeprom.read_array(addr, len(val))
exp_val = val
if val2 != exp_val:
    print("ERROR: write/read_array addr: %s, expected: %s, got: %s" % (addr, exp_val, val2))

val = "ABCDEFGHIJKLMNOPQRSTUVWXZY0123456789___"
addr = 70
l = len(val)-2
eeprom.write_string(addr, val, l)
val2 = eeprom.read_string(addr, l)
exp_val = val[:-2]
if val2 != exp_val:
    print("ERROR: write/read_string addr: %s, expected: %s, got: %s" % (addr, exp_val, val2))



data = eeprom.read_array(0, 256)
print("%s" % data)
s = ""
for i in range(0, len(data)):
    if s != "":
        s += " "
    s = s + hex((data[i]))
    if (i + 1) % 16 == 0:
        print(s)
        s = ""
print(s)


