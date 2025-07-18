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
import yaml
import logging
import asyncio
import websockets
import json
import time
import importlib
import digie35.digie35core as digie35core
import datetime
import os
import signal

class Digie35ServerError(Exception):
    pass

RPI_FLAG = True
try:
    import digie35.digie35rpi
except ImportError:
    RPI_FLAG = False
    print("RPi stuff not found. RPi support disabled")

global xboard

def get_board_memory_class(board_type, board_id = None, version = None):
    if not isinstance(xboard, digie35board.GulpExtensionBoard):
        raise Digie35ServerError("No EEPROM on board")

    if board_type == "XBOARD":
        eeprom = xboard._xboard_memory
    else:
        if board_type == "ADAPTER":
            eeprom = xboard._aot_memory
        elif board_type == "LIGHT":
            eeprom = xboard._light_memory
        else:
            raise Digie35ServerError(f"Unknown board type {board_type}")
        if board_id == None:
            id_ver = eeprom.get_id_version()
        else:
            id = board_id
            if version == None:
                ver = 0
            else:
                ver = version
            id_ver = (id, ver)
        if id_ver == None:
            raise Digie35ServerError("Board not specified")
        logging.getLogger().debug("id: %s, ver: %s" % id_ver)
        adapter_class = digie35board.GulpExtensionBoard.get_adapter_class_by_name(id_ver)
        if adapter_class == None:
            raise Digie35ServerError("Cannot find adapter '%s'" % (id_ver, ))
        eeprom = eeprom.create_adapter_memory(adapter_class)
    return eeprom


WS_PROTOCOL_VERSION = "0.2"

ws_clients = set()

async def ws_handler(websocket, path):
    global ws_clients
    ws_clients.add(websocket)
    try:
        global WS_PROTOCOL_VERSION
        CMD_DELIMITER = "|"
        PARAM_DELIMITER = ":"
        global xboard
        log = logging.getLogger()
        log.debug("path: %s", path)
        while True:
            try:
                data = await websocket.recv()
                log.debug("ws: %s", data)
                l = data.split(PARAM_DELIMITER, 1)
                commands = []
                if len(l) > 1 and len(l[1]) > 0 and l[1][0] == "{":
                    commands.append((l[0].upper(), json.loads(l[1]), ))
                else:
                    l = data.split(CMD_DELIMITER)
                    for cmd_param in l:
                        params = cmd_param.split(PARAM_DELIMITER)
                        cmd = params.pop(0).upper()
                        commands.append((cmd, params))

                reply_status = False
                reply = ""
                reply_data = None
                for cmd_params in commands:
                    log.debug("cmd: %s", cmd_params)
                    cmd = cmd_params[0]
                    params = cmd_params[1]

                    def get_param(num, default):
                        if len(params) > num and params[num].strip() != "":
                            return params[num].strip()
                        else:
                            return default

                    try:
                        if "":
                            pass
                        elif cmd == "LEVEL":
                            xboard.set_io_state(get_param(0, "").lower(), int(get_param(1, 1)))
                            reply_status = True
                        elif cmd == "WAIT":
                            time.sleep(float(get_param(0, "1")))
                            reply_status = True
                        elif cmd == "PULSE":
                            xboard.pulse_output(get_param(0, "").lower(), float(get_param(2, 0)), float(get_param(1, 1)))
                            reply_status = True
                        elif cmd == "SENSOR":
                            xboard.set_io_state(get_param(0, "").lower(), int(get_param(1, 1)))
                            reply_status = True

                        elif cmd == "MOVE":
                            xboard.check_capability("motorized")
                            xboard.get_adapter().set_motor(int(get_param(0, 1)))
                            reply_status = True
                        elif cmd == "STOP":
                            xboard.check_capability("motorized")
                            xboard.get_adapter().set_motor(0)
                            reply_status = True
                        elif cmd == "EJECT":
                            xboard.check_capability("motorized")
                            xboard.get_adapter().eject(int(get_param(0, 1)))
                            reply_status = True
                        elif cmd == "INSERT":
                            xboard.check_capability("motorized")
                            xboard.get_adapter().lead_in()
                            reply_status = True
                        elif cmd == "MOVE_BY":
                            xboard.check_capability("motorized")
                            xboard.get_adapter().move_by(int(get_param(0, 1)), int(get_param(1, 3)))
                            reply_status = True
                        elif cmd == "FLATTEN":
                            xboard.check_capability("flattening")
                            xboard.get_adapter().flatten_plane(int(get_param(0, 1)))

                        elif cmd == "SET_BACKLIGHT":
                            xboard.set_backlight(get_param(0, 1).lower(), int(get_param(1, 1)))

                        elif cmd == "HOTPLUG":
                            xboard.check_connected_adapter()
                            reply_status = True

                        elif cmd == "GET":
                            reply_status = True
                        elif cmd == "HELLO":
                            reply = {
                                "board": xboard.get_id(),
                                "version": __version__,
                                "ws_protocol": WS_PROTOCOL_VERSION,
                                "eeprom": isinstance(xboard, digie35board.GulpExtensionBoard),
                            }
                        elif cmd == "GET_CONFIG":
                            header_map = digie35board.GulpBoardMemory.HEADER_MAP
                            def add_options(map, id, opts):
                                for i in range(len(map)):
                                    if map[i][0] == id and opts:
                                        item = list(map[i])
                                        if len(item) <= 4:
                                            item += [None, ]
                                        if len(item) <= 5:
                                            item += [None, ]
                                        item[5] = opts
                                        map[i] = tuple(item)

                            def add_options_cfg(map, id, cfg_key):
                                if cfg_key in config:
                                    add_options(map, id, config[cfg_key])
                            ts = {}
                            t = datetime.date.today()
                            for i in range(0, 7):
                                t2 = t - datetime.timedelta(days=i*1)
                                y = t2.isocalendar()[0]
                                doy = int(t2.strftime("%j"))
                                # workaround add space to force not sorting numeric keys when parsing in JSON
                                ts["%.2d%.3d " % (y % 100, doy)] = t2.strftime("%d.%m.%Y")
                                #ts.append("%.2d%.3d" % (t2.isocalendar()[0] % 100, int(t2.strftime("%j"))))
                            for i in range(0, 5):
                                t2 = t - datetime.timedelta(days=i*7)
                                y = t2.isocalendar()[0]
                                woy = t2.isocalendar()[1]
                                ts["%.2d%.3d " % (y % 100, woy + 900)] = "%d W:%s" % (y, woy)
                                #ts.append("%.2d%.3d" % (t2.isocalendar()[0] % 100, 900+t2.isocalendar()[1]))

                            add_options(header_map, "version", [i for i in range(104+1, 100, -1)])
                            add_options_cfg(header_map, "pcb_by", "assemblers")
                            add_options_cfg(header_map, "pcba_smd_by", "assemblers")
                            add_options_cfg(header_map, "pcba_tht_by", "assemblers")
                            add_options_cfg(header_map, "tested1_by", "testers")
                            add_options_cfg(header_map, "tested2_by", "testers")
                            add_options(header_map, "pcb_stamp", ts)
                            add_options(header_map, "pcba_smd_stamp", ts)
                            add_options(header_map, "pcba_tht_stamp", ts)
                            add_options(header_map, "tested1_stamp", ts)
                            add_options(header_map, "tested2_stamp", ts)
                            def process_map(map):
                                result = []
                                for item1 in map:
                                    if not item1[0]:
                                        continue
                                    item = list(item1)
                                    if len(item) > 5 and callable(item[5]):
                                        item[5] = item[5]()
                                    result.append(item)
                                return result

                            reply = {
                                "eeprom": {
                                    "COMMON": process_map(header_map),
                                    } | {cls.ID: process_map(cls.BOARD_MEMORY_CLASS.CUSTOM_MAP) for cls in digie35board.registered_boards},
                                "adapter_boards": [cls.ID for cls in digie35board.registered_boards if issubclass(cls, digie35core.Adapter) and not issubclass(cls, digie35board.GulpLightAdapter)],
                                "light_boards": [cls.ID for cls in digie35board.registered_boards if issubclass(cls, digie35board.GulpLightAdapter)],
                            }
                            for id in list(reply["eeprom"]):
                                for i in range(len(reply["eeprom"][id])):
                                    item = list(reply["eeprom"][id][i])
                                    if len(item) > 5 and callable(item[5]):
                                        item[5] = item[5]()
                                    reply["eeprom"][id][i] = tuple(item)
                            break
                        elif cmd == "READ_EEPROM":
                            eeprom = get_board_memory_class(params["board_type"])
                            reply = {
                                "board_type": params["board_type"],
                                "common": eeprom.read_header(),
                                "board": eeprom.read_custom(),
                            }
                        elif cmd == "WRITE_EEPROM":
                            eeprom = get_board_memory_class(params["board_type"], params["common"]["adapter_id"], params["common"]["version"])
                            eeprom.write_header(params["common"])
                            eeprom.write_custom(params["board"])
                            reply = {
                                "board_type": params["board_type"],
                                "common": eeprom.read_header(),
                                "board": eeprom.read_custom(),
                            }
                        elif cmd == "BYE":
                            reply = ""
                            reply_status = False
                            break
                        else:
                            reply = f"Unknown command: {cmd}"

                    except Exception as e:
                        log.error("%s", e, exc_info=True)
                        reply = repr(e)
                        break

                if reply_status and reply == "":
                    reply = xboard.get_state(True)
                if isinstance(reply, (dict, list, set)):
                    reply = json.dumps({"cmd": cmd, "payload": reply})
                log.debug("ws.send: %s" % reply)

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

def on_terminate(signal_no, dummy):
    logging.getLogger().debug(f"Terminate shutdown helper, signal: %d" % (signal_no))
    # force KeyboardInterrupt
    os.kill(os.getpid(), signal.SIGINT)

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

    global config
    config = {}
    if args.configFile:
        log.debug("Loading config file: %s", args.configFile)
        config = yaml.load(args.configFile, Loader=yaml.CLoader)
        log.debug("Configuration: %s", config)

    log.debug("film_xboard_class: %s", film_xboard_class.__name__)
    global xboard
    xboard = film_xboard_class(mainboard, broadcast)

    signal.signal(signal.SIGTERM, on_terminate)

    async def ws_run():
        async with websockets.serve(ws_handler, host=args.wsAddr, port=args.wsPort):
            await asyncio.Future()  # run forever

    try:
        asyncio.run(ws_run())
    except KeyboardInterrupt:
        xboard.reset()
        pass


if __name__ == "__main__":
   main()
