#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-
#
# Copyright (c) 2023 MandySoft
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

__author__ = "Tomas Mandys"
__copyright__ = "Copyright (C) 2023 MandySoft"
__licence__ = "MIT"
__version__ = "0.2"

import argparse
import logging
import locale
import datetime
import digie35.digie35rpi as digie35rpi
import digie35.digie35board as digie35board
import re

def add_arg_opts(argParser, prefix, map):
    pfx = "--" + prefix
    res = []
    for item in map:
        help = item[3]
        choices = None
        if len(item) > 5:
            opts = []
            choices = []
            for opt in item[5]:
                if isinstance(item[5], dict):
                    opts.append("%s..%s" % (opt, item[5][opt]))
                else:
                    opts.append(str(opt))
                if item[1] in ["number", "int"]:
                    choices.append(int(opt))
                else:
                    choices.append(str(opt))
            help += " (" + (", ".join(opts)) + ")"

        if item[0] == None:
            continue
        if item[1] == "string":
            argParser.add_argument(pfx + item[0], help=help, choices=choices)
        elif item[1] == "STRING":
            argParser.add_argument(pfx + item[0], type=str.upper, help=help, choices=choices)
        elif item[1] == "datetime":
            argParser.add_argument(pfx + item[0], action="store_true", help=help, choices=choices)
        elif item[1] in ["number", "int"]:
            argParser.add_argument(pfx + item[0], type=int, help=help, choices=choices)

def process_map(args, prefix, map, write_default, now):
    res = {}
    for item in map:
        if item[0] == None:
            continue
        if hasattr(args, prefix+item[0]):
            val = getattr(args, prefix+item[0])
            if item[1] == "datetime":
                if val:
                    res[item[0]] = now
            else:
                if val != None:
                    res[item[0]] = val
                elif write_default and len(item) > 4 and item[4] != None:
                    res[item[0]] = item[4]
    return res

def main():
    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Digie35 Adapter Config Tool for Gulp boards, v%s" % __version__,
        epilog='''\
EEPROM I2C addresses: xboard: 0x54, AOT adapter: 0x55, light adapter: 0x56

Examples or args:
  main board init
    -b MAIN -w --default --h_version 103 --h_serial_number 123456789
  Stepper adapter init
    -b AOT -w --default --h_adapter_id STEPPER --h_version 103 --h_serial_number 123456789
  Nikon adapter init
    -b AOT -w --default --h_adapter_id NIKON --h_version 103 --h_serial_number 123456789
  Manual adapter init
    -b AOT -w --default --h_adapter_id MANUAL --h_version 103 --h_serial_number 123456789
  Light internal adapter init (white LED only)
    -b LIGHT -w --default --h_adapter_id LGHT8PWM --h_version 103 --h_serial_number 123456789 --la_led1 1
''',
        formatter_class=argparse.RawTextHelpFormatter,
    )
    argParser.add_argument("-b", "--board", choices=["MAIN", "M", "AOT", "A", "LIGHT", "L"], type=str.upper, default="MAIN", help=f"Board type, default: %(default)s")
    argParser.add_argument("-w", "--write", action="store_true", help=f"Write values")
    argParser.add_argument("--erase", action="store_true", help=f"Erase all values first")
    argParser.add_argument("--default", action="store_true", help=f"Write default values not specified as parameter")
    argParser.add_argument("--dry_run", action="store_true", help=f"Do not write physically anything")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("--version", action="version", version=f"%s" % __version__)

    maps = [
        # prefix, layout
        ("h_", digie35board.GulpBoardMemory),
        ("b_", digie35board.GulpExtensionBoardMemory),
        ("na_", digie35board.GulpNikonStepperMotorAdapterMemory),
        ("sa_", digie35board.GulpStepperMotorAdapterMemory),
        ("ma_", digie35board.GulpManualAdapterMemory),
        ("la_", digie35board.GulpLightAdapterMemory),
    ]

    add_arg_opts(argParser, maps[0][0], maps[0][1].HEADER_MAP)
    for item in maps:
        add_arg_opts(argParser, item[0], item[1].CUSTOM_MAP)

    args = argParser.parse_args()
    LOGGING_FORMAT = "%(asctime)s: %(name)s: %(levelname)s: %(message)s"
    logging.basicConfig(format=LOGGING_FORMAT)
    log = logging.getLogger()

    # logging.NOTSET logs everything
    verbose2level = (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)
    args.verbose = min(max(args.verbose, 0), len(verbose2level) - 1)
    log.setLevel(verbose2level[args.verbose])

    log.debug("Parsed args: %s", args)

    bus_id = 1
    mainboard = digie35rpi.RpiMainboard(True)
    xboard = digie35board.GulpExtensionBoard(mainboard, None)
    if args.board[0] != "M":
        if args.board[0] == "A":
            eeprom = xboard._aot_memory
        #elif args.board[0] == "L":
        else:
            eeprom = xboard._light_memory
        if args.h_adapter_id == None:
            id_ver = eeprom.get_id_version()
        else:
            id = args.h_adapter_id
            if args.h_version == None:
                ver = 0
            else:
                ver = args.h_version
            id_ver = (id, ver)
        if id_ver == None:
            print("Adapter not specified")
            exit()
        print("id: %s, ver: %s" % id_ver)
        adapter_class = digie35board.GulpExtensionBoard.get_adapter_class_by_name(id_ver)
        if adapter_class == None:
            print("Cannot find adapter '%s'" % (id_ver, ))
            exit()
        eeprom = eeprom.create_adapter_memory(adapter_class)
    else:
        eeprom = xboard._xboard_memory
    log.debug("Bus_id: %s, i2c_addr: 0x%x", bus_id, eeprom._i2c_addr)

    old_header = eeprom.read_header()
    old_custom = eeprom.read_custom()
    if not args.write:
        print(old_header)
        print(old_custom)
        exit()

    log.debug("Old header: %s", old_header)
    log.debug("Old custom: %s", old_custom)

    now = datetime.datetime.now()

    new_header = process_map(args, maps[0][0], eeprom.HEADER_MAP, args.default, now)
    # what prefix is related to current eeprom ?
    new_custom = {}
    unknown = []
    for item in maps:
        if isinstance(eeprom, item[1]):
            new_custom = process_map(args, item[0], eeprom.CUSTOM_MAP, args.default, now)
        else:
            # test options related to board. Args parser knows all
            h = process_map(args, item[0], item[1].CUSTOM_MAP, False, now)
            if h != {}:
                for p in list(h):
                    unknown.append(item[0]+p)

    if unknown != []:
        print("Params non related to current board %s" % (unknown) )
        exit()

    if args.erase:
        log.debug("Erasing memory")
        if not args.dry_run:
            eeprom.erase()
        else:
            print("DRY RUN: erase memory")
    if new_header == {} and new_custom == {}:
        log.debug("No data provided, skipping write")
        exit()

    if new_header != {}:
        log.debug("Writing new header: %s", new_header)
        if not args.dry_run:
            eeprom.write_header(new_header)
        else:
            log.debug("Header to be written: %s", new_header)
    if new_custom != {}:
        log.debug("Writing new custom: %s", new_custom)
        if not args.dry_run:
            eeprom.write_custom(new_custom)
        else:
            log.debug("Custom to be written: %s", new_custom)

    h = eeprom.read_header()
    log.debug("Header: %s", h)
    h = eeprom.read_custom()
    log.debug("Custom: %s", h)


if __name__ == "__main__":
   main()
