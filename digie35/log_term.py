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

tmbx__author__ = "Tomas Mandys"
__copyright__ = "Copyright (C) 2025 MandySoft"
__licence__ = "MIT"
__version__ = "0.8"

import argparse
import locale
import websockets
import asyncio
import logging
import sys

async def listen_and_send(uri):
    logging.getLogger().info("Connecting URI: %s" % (uri))
    async with websockets.connect(uri) as websocket:
        async def receive_messages():
            while True:
                msg = await websocket.recv()
                print(msg)

        async def send_messages():
            while True:
                message = await asyncio.to_thread(sys.stdin.readline)
                await websocket.send(message)

        await asyncio.gather(receive_messages(), send_messages())

def main():
    VERSION_INFO = {
        "program": "wsclient",
        "version": __version__,
    }
    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Websocket client, v%s" % __version__,
        epilog="Use command 'VERBOSE:<level>' to change server verbosity [0..6]",
    )
    argParser.add_argument("ws_uri", nargs="?", default="ws://localhost:8401", help=f"Websocket server to connect, default: %(default)s")
    argParser.add_argument("-v", "--verbose", action="count", default=1, help="verbose output")
    argParser.add_argument("--version", action="version", version=f"%s" % VERSION_INFO)

    args = argParser.parse_args()

    verbose2level = (logging.INFO, logging.DEBUG)
    if args.verbose:
        level = min(max(args.verbose, 0), len(verbose2level) - 1)
        logging.getLogger().setLevel(verbose2level[level-1])

    LOGGING_FORMAT = "%(message)s"
    logging.basicConfig(format=LOGGING_FORMAT)

    logging.getLogger().info("URI: %s" % (args.ws_uri))
    try:
        asyncio.run(listen_and_send(args.ws_uri))
    except KeyboardInterrupt:
        logging.getLogger().debug("Keyboard interrupt")

if __name__ == "__main__":
   main()
