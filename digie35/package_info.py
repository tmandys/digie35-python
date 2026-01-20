#!/usr/bin/env python3
# vim: set expandtab:
# -*- coding: utf-8 -*-

import sys
import os
from importlib import metadata

# print info about wheel source which might be .whl or source directory in case of development

DEFAULT_PACKAGE = "digie35_ctrl"

def package_info(name: str):
    try:
        dist = metadata.distribution(name)
        print(f"Name: {dist.metadata['name']}")
        print(f"Version: {dist.version}")
        location = dist.locate_file('')
        print(f"Installed from: {location}")
        editable = os.path.exists(os.path.join(location, name, "__init__.py"))
        print(f"Editable install: {editable}")
    except metadata.PackageNotFoundError:
        print(f"Package '{name}' not found")

if __name__ == "__main__":
    pkg_name = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PACKAGE
    package_info(pkg_name)
