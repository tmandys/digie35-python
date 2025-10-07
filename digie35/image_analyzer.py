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

def int_0_100(value):
    ivalue = int(value)
    if ivalue <= 0 or ivalue > 100:
        raise argparse.ArgumentTypeError(f"{value} range error (0-100>")
    return ivalue

def main():
    VERSION_INFO = f"OpenCV version: {cv2.__version__}, file: {cv2.__file__}, digie2image: {digie35image.__version__}"
    verbose2level = (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG, logging.DEBUG-1, logging.DEBUG-2, )

    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Digie35 image analyzer, v%s" % __version__,
        epilog="",
    )
    argParser.add_argument("filename", nargs="+", help="Input image file name")
    argParser.add_argument("-t", "--task", dest="task", choices=["FRAME", "MEAN_RGB", "UNIFORMITY"], type=str.upper, default="FRAME", help=f"Select task to be performed. Default: %(default)s")
    argParser.add_argument("-i", "--show-input-image", dest="show_input_image", action="store_true", help="show original image to be analyzed")

    frame_group = argParser.add_argument_group(
        title="Frame options",
        description="Process image and analyze focus, frames, preforation, negative/positive, ...",
    )
    frame_group.add_argument("-o", "--show-output-image", dest="show_output_image", action="store_true", help="show annotated image")
    frame_group.add_argument("-s", "--save-output-image", dest="save_output_image", action="store_true", help="save annotated image to the same location as original image with '.output' suffix")
    frame_group.add_argument("-j", "--save-result", dest="save_result", action="store_true", help="save json result to the same location as original image with '.output.json' suffix")
    frame_group.add_argument("-a", "--append-result", dest="append_result", action="store_true", help="append json result to the same location as original image into .json file")

    mean_rgb_group = argParser.add_argument_group(
        title="Mean RGB options",
        description="Calculate RGB intensity in center of image to calibrate LED illumination",
#        epilog='''\
#Examples or args:
#''',
#        formatter_class=argparse.RawTextHelpFormatter,
    )
    mean_rgb_group.add_argument("--mrgb-fraction", dest="mean_rgb_fraction", type=int_0_100, default=20, help=f"Percent size of image to evaluate in center. Default: %(default)s")

    uniformity_group = argParser.add_argument_group(
        title="Illumination uniformity options",
        description="Calcalate intensity in grid matrix to consider illumination intensity",
    )
    uniformity_group.add_argument("--uni-grid", dest="uni_grid", type=int_0_100, default=20, help=f"Grid matrix size. Default: %(default)s")

    argParser.add_argument("-q", "--quiet", dest="quiet", action="store_true", help="do not print JSON annotations")
    argParser.add_argument("-l", "--logfile", dest="logFile", metavar="FILEPATH", help="logging file, default: stderr")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("--version", action="version", version=f"%s" % VERSION_INFO)

    args = argParser.parse_args()

    #globals()["digie35image"] = importlib.import_module("digie35.digie35image")

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
        for filename in args.filename:
            logging.getLogger().info(f"Input image: {filename}")
            with open(filename, "rb") as f:
                image_data = f.read()
            logging.getLogger().debug(f"Header: {image_data[:10]}")

            analyzer = digie35image.ImageAnalysis(image_data, filename)
            if args.show_input_image:
                digie35image.show_image(analyzer._image, "Input image")

            if args.task == "FRAME":
                analyzer.analyze()

                if not args.quiet:
                    print(json.dumps(analyzer.get_result(), indent=2, ensure_ascii=False, cls=digie35image.NumpyEncoder))

                if args.show_output_image:
                    digie35image.show_image(analyzer.get_output_image(), "Output image")

                if args.save_output_image:
                    path = Path(filename)
                    out_path = str(path.with_name(path.stem + ".output" + path.suffix))
                    logging.getLogger().info(f"Output image: {out_path}")
                    cv2.imwrite(out_path, analyzer.get_output_image())

                if args.save_result:
                    path = Path(filename)
                    out_path = str(path.with_name(path.stem + ".output.json"))
                    logging.getLogger().info(f"Output result: {out_path}")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(json.dumps(analyzer.get_result(), indent=2, ensure_ascii=False, cls=digie35image.NumpyEncoder))

                if args.append_result:
                    path = Path(filename)
                    out_path = str(path.with_name(path.stem + ".json"))
                    if path.exists():
                        logging.getLogger().info(f"Append result to to json: {out_path}")
                        with open(out_path, "r", encoding="utf-8") as f:
                            data = json.load(f);
                        data["vision"] = analyzer.get_result()
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(json.dumps(data, indent=2, ensure_ascii=False, cls=digie35image.NumpyEncoder))
                    else:
                        logging.getLogger().info(f"Json file does not exists: {out_path}")
            elif args.task == "MEAN_RGB":
                result = analyzer.analyze_rgb_intensity(args.mean_rgb_fraction/100)
                print(f"{result}")
            elif args.task == "UNIFORMITY":
                result = analyzer.analyze_uniformity(args.uni_grid)
                arr_str = [[f"{v:.2f}" for v in row] for row in result[1]]
                print(f"{result[0]:3f}")
                print(f"{arr_str}")

    except KeyboardInterrupt:
        print("Keyboard interrupt, shutdown")

    cv2.destroyAllWindows()

if __name__ == "__main__":
   main()
