#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-
#
# Copyright (c) 2025 MandySoft
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
__copyright__ = "Copyright (C) 2025 MandySoft"
__licence__ = "MIT"
__version__ = "0.1"

import argparse
import locale
import json
import logging
import digie35.digie35image as digie35image
import cv2
import numpy as np
from pathlib import Path

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        return super().default(obj)

def main():
    VERSION_INFO = f"OpenCV version: {cv2.__version__}, file: {cv2.__file__}, digie2image: {digie35image.__version__}"
    verbose2level = (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG, logging.DEBUG-1, logging.DEBUG-2, )

    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Digie35 image analyzer, v%s" % __version__,
        epilog="",
    )
    argParser.add_argument("filename", help="Input image file name")  # nargs="+"
    argParser.add_argument("-i", "--show-input-image", dest="show_input_image", action="store_true", help="show original image to be analyzed")
    argParser.add_argument("-o", "--show-output-image", dest="show_output_image", action="store_true", help="show annotated image")
    argParser.add_argument("-s", "--save-output-image", dest="save_output_image", action="store_true", help="save annotated image to the same location as original image with '.output' suffix")
    argParser.add_argument("-j", "--save-result", dest="save_result", action="store_true", help="save json result to the same location as original image with '.output.json' suffix")
    argParser.add_argument("-q", "--quiet", dest="quiet", action="store_true", help="do not print JSON annotations")
    argParser.add_argument("-l", "--logfile", dest="logFile", metavar="FILEPATH", help="logging file, default: stderr")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("--version", action="version", version=f"%s" % VERSION_INFO)

    args = argParser.parse_args()
    LOGGING_FORMAT = "%(asctime)s: %(name)s: %(threadName)s: %(levelname)s: %(message)s"
    if args.logFile:
        logging.basicConfig(filename=args.logFile, format=LOGGING_FORMAT)
    else:
        logging.basicConfig(format=LOGGING_FORMAT)
    logging.raiseExceptions = False  # do not raise exceptions when already handling exception, see logging.handleError
    if not args.verbose:  # when specified action="count" then default > 0 is useless
        args.verbose = 2
    level = min(max(args.verbose, 0), len(verbose2level) - 1)
    logging.getLogger().setLevel(verbose2level[level])
    logging.getLogger().debug("Verbosity: %s(%s)" % (level, logging.getLogger().getEffectiveLevel()))
    try:
        logging.getLogger().info(f"Input image: {args.filename}")
        with open(args.filename, "rb") as f:
            image_data = f.read()
        logging.getLogger().debug(f"Header: {image_data[:10]}")

        analyzer = digie35image.ImageAnalysis(image_data, args.filename)
        if args.show_input_image:
            digie35image.show_image(analyzer._image, "Input image")

        analyzer.analyze()

        if not args.quiet:
            print(json.dumps(analyzer.get_result(), indent=2, ensure_ascii=False, cls=NumpyEncoder))

        if args.show_output_image:
            digie35image.show_image(analyzer.get_output_image(), "Output image")

        if args.save_output_image:
            path = Path(args.filename)
            out_path = str(path.with_name(path.stem + ".output" + path.suffix))
            logging.getLogger().info(f"Output image: {out_path}")
            cv2.imwrite(out_path, analyzer.get_output_image())

        if args.save_result:
            path = Path(args.filename)
            out_path = str(path.with_name(path.stem + ".output.json"))
            logging.getLogger().info(f"Output result: {out_path}")
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(analyzer.get_result(), indent=2, ensure_ascii=False, cls=NumpyEncoder))

    except KeyboardInterrupt:
        print("Keyboard interrupt, shutdown")

    cv2.destroyAllWindows()

if __name__ == "__main__":
   main()
