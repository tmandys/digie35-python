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
__version__ = "0.8"

import sys
import argparse
#import yaml
import logging
import asyncio
import websockets
import json
import time
import importlib
import digie35.digie35core as digie35core

RPI_FLAG = True
try:
    import digie35.digie35rpi
except ImportError:
    RPI_FLAG = False
    print("RPi stuff not found. RPi support disabled")

def get_options(header_map):
    return header_map
def get_board_options(board_class):
    header_map = board_class.ADAPTER_MEMORY_CLASS.HEADER_MAP

    return 

WS_PROTOCOL_VERSION = "0.2"

ws_clients = set()

async def ws_handler(websocket, path):
    global ws_clients
    ws_clients.add(websocket)
    try:
        global WS_PROTOCOL_VERSION
        CMD_DELIMITER = "|"
        PARAM_DELIMITER = ":"
        global digitizer
        log = logging.getLogger()
        log.debug("path: %s", path)
        while True:
            try:
                data = await websocket.recv()
                log.debug("ws: %s", data)
                cmds = data.split(CMD_DELIMITER)
                reply_status = False
                reply = ""
                reply_data = None
                for cmd_params in cmds:
                    log.debug("cmd: %s", cmd_params)
                    params = cmd_params.split(PARAM_DELIMITER)
                    cmd = params.pop(0).upper()

                    def get_param(num, default):
                        if len(params) > num and params[num].strip() != "":
                            return params[num].strip()
                        else:
                            return default

                    try:
                        if "":
                            pass
                        elif cmd == "LEVEL":
                            digitizer.set_io_state(get_param(0, "").lower(), int(get_param(1, 1)))
                            reply_status = True
                        elif cmd == "WAIT":
                            time.sleep(float(get_param(0, "1")))
                            reply_status = True
                        elif cmd == "PULSE":
                            digitizer.pulse_output(get_param(0, "").lower(), float(get_param(2, 0)), float(get_param(1, 1)))
                            reply_status = True
                        elif cmd == "SENSOR":
                            digitizer.set_io_state(get_param(0, "").lower(), int(get_param(1, 1)))
                            reply_status = True

                        elif cmd == "MOVE":
                            digitizer.check_capability("motorized")
                            digitizer.get_adapter().set_motor(int(get_param(0, 1)))
                            reply_status = True
                        elif cmd == "STOP":
                            digitizer.check_capability("motorized")
                            digitizer.get_adapter().set_motor(0)
                            reply_status = True
                        elif cmd == "EJECT":
                            digitizer.check_capability("motorized")
                            digitizer.get_adapter().eject(int(get_param(0, 1)))
                            reply_status = True
                        elif cmd == "INSERT":
                            digitizer.check_capability("motorized")
                            digitizer.get_adapter().lead_in()
                            reply_status = True
                        elif cmd == "MOVE_BY":
                            digitizer.check_capability("motorized")
                            digitizer.get_adapter().move_by(int(get_param(0, 1)), int(get_param(1, 3)))
                            reply_status = True

                        elif cmd == "SET_BACKLIGHT":
                            digitizer.set_backlight(get_param(0, 1).lower(), int(get_param(1, 1)))

                        elif cmd == "HOTPLUG":
                            digitizer.check_connected_adapter()
                            reply_status = True

                        elif cmd == "GET":
                            reply_status = True
                        elif cmd == "HELLO":
                            reply = f"%s:protocol v%s" % (digitizer.get_id(), WS_PROTOCOL_VERSION)
                        elif cmd == "GET_CONFIG":
                            reply = {
                                "eeprom": {
                                    "HEADER": digie35board.GulpBoardMemory.HEADER_MAP,
                                    "MAIN": digie35board.GulpExtensionBoardMemory.CUSTOM_MAP,
                                    digie35board.GulpNikonStepperMotorAdapter.ID: digie35board.GulpNikonStepperMotorAdapterMemory.CUSTOM_MAP,
                                    digie35board.GulpStepperMotorAdapter.ID: digie35board.GulpStepperMotorAdapterMemory.CUSTOM_MAP,
                                    digie35board.GulpManualAdapter.ID: digie35board.GulpManualAdapterMemory.CUSTOM_MAP,
                                    digie35board.GulpLight8xPWMAdapter.ID: digie35board.GulpLightAdapterMemory.CUSTOM_MAP,
                                },
                                "adapter_boards": [
                                    digie35board.GulpNikonStepperMotorAdapter.ID,
                                    digie35board.GulpStepperMotorAdapter.ID,
                                    digie35board.GulpManualAdapter.ID,
                                ],
                                "light_boards": [
                                    digie35board.GulpLight8xPWMAdapter.ID,
                                ],
                            }
                            break
                        elif cmd == "BYE":
                            reply = ""
                            reply_status = False
                            break
                        else:
                            reply = f"Unknown command: {cmd}"

                    except Exception as e:
                        log.error("%s", repr(e))
                        reply = repr(e)
                        break

                if reply_status and reply == "":
                    state = digitizer.get_state(True)
                    reply = state
                reply = json.dumps({"cmd": cmd, "payload": reply})

                await websocket.send(reply)
            except websockets.exceptions.ConnectionClosedError:
                log.error("Connection closed")
                break
            except websockets.exceptions.ConnectionClosedOK:
                break
    finally:
        ws_clients.remove(websocket)

async def send(websocket, message):
    try:
        await websocket.send(json.dumps(message))
    except websockets.ConnectionClosed:
        pass

def broadcast(message):
    global ws_clients
    logging.getLogger().debug("broadcast: %s", message)
    for websocket in ws_clients.copy():
        asyncio.run(send(websocket, message))

def main():
    VERSION = "0.1.0"
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Film Scanner Control for Raspberry Pi, v%s" % VERSION,
        epilog="",
    )
    argParser.add_argument("-c", "--config", dest="configFile", metavar="FILEPATH", type=argparse.FileType('r'), help="Raspberry PI+HAT configuration file in YAML")
    argParser.add_argument("-l", "--logfile", dest="logFile", metavar="FILEPATH", help="Logging file, default: stderr")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("-b", "--board", choices=["HEAD", "GULP", "NIKI", "ALPHA"], type=str.upper, default="HEAD", help=f"Board name, default: %(default)s")
    argParser.add_argument("-m", "--mainboard", choices=["GPIOZERO", "RPIGPIO", "SIMULATOR",], type=str.upper, default="GPIOZERO", help=f"Mainboard library name, default: %(default)s")
    argParser.add_argument("-w", "--addr", dest="wsAddr", metavar="ADDR", default="localhost", help=f"Websocket listener bind address ('0.0.0.0' = all addresses), default: %(default)s")
    argParser.add_argument("-p", "--port", dest="wsPort", metavar="PORT", type=int, default=8401, help=f"Websocket listener port, default: %(default)s")
    argParser.add_argument("--version", action="version", version=f"%s, control: %s, ws protocol: v%s" % (VERSION, digie35core.ExtensionBoard.VERSION, WS_PROTOCOL_VERSION))

    args = argParser.parse_args()
    LOGGING_FORMAT = "%(asctime)s: %(levelname)s: %(message)s"
    if args.logFile:
        logging.basicConfig(filename=args.logFile, format=LOGGING_FORMAT)
    else:
        logging.basicConfig(format=LOGGING_FORMAT)
    log = logging.getLogger()
    # logging.NOTSET logs everything
    verbose2level = (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)
    args.verbose = min(max(args.verbose, 0), len(verbose2level) - 1)
    log.setLevel(verbose2level[args.verbose])

    log.debug("Parsed args: %s", args)

    board = args.board.upper()
    if args.mainboard == "SIMULATOR":
        module2 = importlib.import_module("digie35.digie35simulator")
        mainboard = module2.SimulatorMainboard()
    elif args.mainboard == "GPIOZERO":
        module2 = importlib.import_module("digie35.digie35gpiozero")
        mainboard = module2.GpioZeroMainboard(board != "NIKI")
    else:
        module2 = importlib.import_module("digie35.digie35rpigpio")
        mainboard = module2.RpiGpioMainboard(board != "NIKI")

    global digie35board
    digie35board = importlib.import_module("digie35.digie35board")
    if board == "ALPHA":
        film_xboard_class = digie35board.AlphalExtensionBoard
    elif board == "NIKI":
        film_xboard_class = digie35board.NikiExtensionBoard
    else:   # GULP
        film_xboard_class = digie35board.GulpExtensionBoard.get_xboard_class(mainboard)

    if args.configFile:
        log.debug("Loading config file: %s", args.configFile)
        cfg = yaml.load(args.configFile, Loader=yaml.CLoader)
        log.debug("Configuration: %s", cfg)

    global digitizer
    log.debug("film_xboard_class: %s", film_xboard_class.__name__)
    digitizer = film_xboard_class(mainboard, broadcast)

    async def ws_run():
        async with websockets.serve(ws_handler, host=args.wsAddr, port=args.wsPort):
            await asyncio.Future()  # run forever

    try:
        asyncio.run(ws_run())
    except KeyboardInterrupt:
        digitizer.reset()
        pass


if __name__ == "__main__":
   main()
