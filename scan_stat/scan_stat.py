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
__version__ = "0.1"

import sys
import argparse
import logging
import time
import locale
import os
import datetime
import re
from wcmatch import glob
import stat
import errno
import csv
import importlib

PWD_FLAG = True
try:
    import pwd
except ImportError:
    PWD_FLAG = False
    print("pwd stuff not found.")

class ScanStatError(Exception):
    pass

def main():
    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Scan statistics by file owner and creation time, v%s" % __version__,
        epilog="",
        #formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    script_directory = os.path.dirname(os.path.abspath(sys.argv[0]))

    argParser.add_argument("-c", "--chart", dest="chartFile", metavar="FILEPATH", type=argparse.FileType('r+'), default=os.path.join(script_directory, "scan_stat_chart.html"), help=f"Chart template, default: '%(default)s'")
    argParser.add_argument("-R", "--rootdir", dest="root_dir", metavar="PATH", default="/media/pi", help=f"Root directory for scanenv variables are supported, e.g.$HOME/.digie35/projects , default: '%(default)s'")
    argParser.add_argument("-P", "--pattern", metavar="string", default="**/*.{ARW,CRW,CR2,CR3,NEF}", help=f"Python wcmatch syntax to recursively scan directories for list of extensions, default: '%(default)s'")
    argParser.add_argument("-H", "--hours", type=int, default=14*24, metavar="hrs", help=f"Period in hour database, default: %(default)s")
    argParser.add_argument("-D", "--days", type=int, default=50, metavar="hrs", help=f"Period in day database, default: %(default)s")
    argParser.add_argument("-W", "--weeks", type=int, default=50, metavar="hrs", help=f"Period in week database, default: %(default)s")
    argParser.add_argument("-M", "--months", type=int, default=0, metavar="hrs", help=f"Period in month database, default: %(default)s")
    argParser.add_argument("-r", "--rerun", action="store_true", help="Reprocess all directory structure")
    argParser.add_argument("-d", "--dryrun", action="store_true", help="Dry run")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("-l", "--logfile", dest="logFile", metavar="FILEPATH", help="Logging file, default: stderr")
    argParser.add_argument("--version", action="version", version=f"%s" % __version__)

    args = argParser.parse_args()
    LOGGING_FORMAT = "%(asctime)s: %(name)s: %(threadName)s: %(levelname)s: %(message)s"
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

    # get file content and parse injected data
    chartContent = args.chartFile.read()
    tags = {}

    period_defs = {
        "HOURLY": {
            "period": args.hours * 60 * 60,
            "stamp_format": "%Y-%m-%d %H:%M",
        },
        "DAILY": {
            "period": args.days * 60 * 60 * 24,
            "stamp_format": "%Y-%m-%d",
        },
        "WEEKLY": {
            "period": args.weeks * 60 * 60 * 24 * 7,
            "stamp_format": "%Y-W%W", # ISO week number
        },
        "MONTHLY": {
            "period": args.months * 60 * 60 * 24 * 31,
            "stamp_format": "%Y-%m",
        },
    }
    for tag in ["DIRS", "HOURLY", "DAILY", "WEEKLY", "MONTHLY"]:
        tags[tag] = {
            "start": "// <__CSV_"+tag+"__>",
            "end": "// </__CSV_"+tag+"__>",
        }

        i = chartContent.find(tags[tag]["start"])
        if i < 0:
            raise ScanStatError("Start tag not found for %s" % (tag))
        i += len(tags[tag]["start"])
        j = chartContent.find(tags[tag]["end"], i)
        if j < 0:
            raise ScanStatError("End tag not found for %s" % (tag))
        lines = []
        lines1 = chartContent[i: j].splitlines()
        chartContent = chartContent[:i] + chartContent[j:]
        if not args.rerun:
            for k in range(0, len(lines1)):
                line = lines1[k]
                if line != "":
                    lines.append(line)
            if len(lines) > 0 and lines[0][0] == "`":
                lines[0] = lines[0][1:]
            if len(lines) > 0 and lines[len(lines)-1][0] == "`":
                lines.pop(len(lines)-1)
            if tag != "DIRS":
                tags[tag]["lines"] = list(csv.reader(lines, delimiter=";"))
            else:
                tags[tag]["lines"] = lines
        else:
            tags[tag]["lines"] = lines
        log.debug("Tag %s\n%s", tag, tags[tag]["lines"])

    log.debug("chartContent without data: %s", chartContent)

    # get files matching pattern
    root_dir = os.path.abspath(os.path.expandvars(args.root_dir))
    log.debug("Root dir: %s, Pattern: %s", root_dir, args.pattern)
    files1 = glob.glob(args.pattern, flags=glob.BRACE|glob.GLOBSTAR|glob.IGNORECASE, root_dir=root_dir)
    log.debug("Files: %s", len(files1))

    # filter out already processed directories
    processed_dirs = {}
    scanned_dirs = {}
    for dir in tags["DIRS"]["lines"]:
        processed_dirs[dir] = False
    for filename in files1:
        dirname = os.path.dirname(filename)
        dirname = dirname.replace("\\", "/")  # backslash is escape char in Javascript
        if not dirname in processed_dirs or args.rerun:
            path = os.path.join(root_dir, filename)
            stat = os.stat(path)
            if stat.st_size > 0:
                if stat.st_uid > 0 and PWD_FLAG:
                    user = pwd.getpwuid(stat.st_uid)
                    user = user.pw_name
                else:
                    user = "pi"
                dt = datetime.datetime.fromtimestamp(stat.st_ctime)
                dtw = dt - datetime.timedelta(days=dt.weekday())
                stamps = {
                    "HOURLY":
                        datetime.datetime(dt.year, dt.month, dt.day, dt.hour, 0),
                    "DAILY":
                        datetime.datetime(dt.year, dt.month, dt.day),
                    "WEEKLY":
                        datetime.datetime(dtw.year, dtw.month, dtw.day),
                    "MONTHLY":
                        datetime.datetime(dt.year, dt.month, 1),
                }
                for tag in list(stamps):
                    s = stamps[tag].strftime(period_defs[tag]["stamp_format"])
                    found = False
                    for line_no in range(0, len(tags[tag]["lines"])):
                        if tags[tag]["lines"][line_no][0] == s and tags[tag]["lines"][line_no][1] == user:
                            tags[tag]["lines"][line_no][2] = int(tags[tag]["lines"][line_no][2]) + 1
                            found = True
                    if not found:
                        tags[tag]["lines"].append([s, user, 1])
                scanned_dirs[dirname] = True

    tags["DIRS"]["lines"] += list(scanned_dirs)

    # squeeze data
    for tag in list(period_defs):
        delta = datetime.timedelta(seconds=period_defs[tag]["period"])
        if period_defs[tag]["period"] > 0:
            lines = []
            fmt = period_defs[tag]["stamp_format"]
            # https://stackoverflow.com/questions/17087314/get-date-from-week-number
            l = fmt.find("%W")
            if l >= 0:
                fmt += "-%w"
            for line in tags[tag]["lines"]:
                s = line[0]
                if l >= 0:
                    s += "-1"
                stamp = datetime.datetime.strptime(s, fmt)
                if stamp + delta >= datetime.datetime.now():
                    lines.append(line)
                else:
                    log.debug("Remove %s: %s", tag, line[0])
        else:
            lines = tags[tag]["lines"]

        def sort_func(item):
            return item[0]

        lines.sort(key=sort_func)
        tags[tag]["lines"] = lines

    for tag in list(tags):
        log.debug("Stat: %s: %s", tag, tags[tag]["lines"])
        i = chartContent.find(tags[tag]["start"])
        i += len(tags[tag]["start"])
        lines = []
        for line in tags[tag]["lines"]:
            if type(line) is list:
                line[2] = str(line[2])
                line = ";".join(line)
            lines.append(line)
        if len(lines) > 0:
            s = "`" + ("\n".join(lines)) + "\n`"
        else:
            s = "``"
        chartContent = chartContent[:i] + "\n" + s + "\n" + chartContent[i:]

    #log.debug("chartContent with new data: %s", chartContent)
    if not args.dryrun:
        log.debug("Write to chartfile")
        args.chartFile.seek(0)
        args.chartFile.truncate()
        args.chartFile.write(chartContent)


if __name__ == "__main__":
   main()
