#!/usr/bin/env python3
# vim: set expandtab:
# -*- coding: utf-8 -*-
#
# Copyright (c) 2024 MandySoft
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

import subprocess
import logging
import argparse
import re
import os
import sys
import locale
import shutil
from packaging.version import Version, InvalidVersion
from packaging.utils import parse_wheel_filename, InvalidWheelFilename, canonicalize_name


package_name = "digie35_ctrl"
python_repository_url = "https://repos.digie35.com/python/"

def main():
    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Camera Control upgrade tool, v%s" % __version__,
        epilog="",
    )
    argParser.add_argument("-f", "--force", action="store_true", help="Force reinstall package")
    argParser.add_argument("-c", "--check", action="store_true", help="Check if new version is available")
    argParser.add_argument("-r", "--release", type=str, default="", help="Install specific version")
    argParser.add_argument("-v", "--verbose", action="count", default=3, help="verbose output")
    argParser.add_argument("--dry_run", action="store_true", help="Do not actually install anything")
    argParser.add_argument("--version", action="version", version=f"%s" % __version__)

    args = argParser.parse_args()
    LOGGING_FORMAT = "%(message)s"
    logging.basicConfig(format=LOGGING_FORMAT)
    verbose2level = (logging.CRITICAL, logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG)
    args.verbose = min(max(args.verbose, 0), len(verbose2level) - 1)
    logging.getLogger().setLevel(verbose2level[args.verbose])

    logging.getLogger().debug("Parsed args: %s", args)

    def run(args, pass_returncode = [], capture_output = True):
        logging.getLogger().debug("Run: %s" % (args))
        proc = subprocess.run(args, capture_output=capture_output)
        logging.getLogger().debug("Response: %s" % (proc))
        if proc.stdout != None:
            proc.stdout = proc.stdout.decode("utf-8")
        if proc.stderr != None:
            proc.stderr = proc.stderr.decode("utf-8")
        if proc.returncode == 0 or proc.returncode in pass_returncode:
            return proc
        logging.getLogger().error("%s" % (proc.stderr))
        sys.exit(127)

    # check installed package
    proc = run([sys.executable, "-m", "pip", "show", package_name])

    ver = re.findall("^Version: *(.*)$", proc.stdout, re.MULTILINE)[0]
    logging.getLogger().info("Found %s installed release pip" % (ver))
    installed_package_version = Version(ver)

    # get available packages
    logging.getLogger().info("Checking remote repository: %s" % (python_repository_url))
    proc = run(["curl", python_repository_url])
    release_files = re.findall(r'href="('+re.escape(package_name)+r'[^"/]+\.whl)"', proc.stdout)
    logging.getLogger().debug("Files: %s" % (release_files))


    logging.getLogger().debug("Looking for %s package" % (args.release if args.release != "" else "LATEST"))
    try:
        requested_version = Version(args.release) if args.release != "" and not args.check else None
    except InvalidVersion:
        argParser.error("Invalid release version: %s" % args.release)
    install_version = None
    install_file = None

    for file in release_files:
        try:
            name, ver, build, tags = parse_wheel_filename(file)
        except InvalidWheelFilename:
            logging.getLogger().warning("Skipping invalid wheel filename: %s", file)
            continue
        if name != canonicalize_name(package_name):
            continue
        if args.release == "" or args.check:
            if install_version is None or ver > install_version:
                install_file = file
                install_version = ver
        else:
            if requested_version == ver:
                install_file = file
                install_version = ver
                break

    if install_file == None:
        logging.getLogger().error("Error: Cannot find package")
        sys.exit(2)

    if args.check:
        if install_version > installed_package_version:
            print("Found newer version: %s" % (install_file))
        else:
            print("No newer version was found")
        sys.exit(0)

    if args.release == "" and install_version < installed_package_version:
        print("Nothing to do, installed version is newer than the repository")
        return

    if installed_package_version == install_version and not args.force:
        logging.getLogger().info("Package already installed: %s" % (install_file))
        print("Nothing to do, package is up to date")
        return

    params = [sys.executable, "-m", "pip", "install"]

    if (args.force):
        params.append("--force-reinstall")
        params.append("--no-dependencies")

    if args.verbose > 3:
        params.append("-v")

    if args.dry_run:
        params.append("--dry-run")

    params.append(python_repository_url+install_file)
    proc = run(params, capture_output=False)

    if not args.dry_run:
        params = [sys.executable, "-m", "digie35.install", "--install", "--restart_services"]
        if args.verbose > 2:
            params.append("-v")
        run(params, capture_output=False)


if __name__ == "__main__":
   main()
