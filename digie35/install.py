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

from subprocess import run
import argparse
import os
import sys
import locale
import shutil

def main():
    locale.setlocale(locale.LC_ALL, 'C')
    argParser = argparse.ArgumentParser(
        #prog=,
        description="Camera Control install/uninstall systemd and http server stuff, v%s" % __version__,
        epilog="",
    )
    WWW_DIR="/var/www/html"
    NGINX_CONF_DIR="/etc/nginx"
    boards = ["HEAD", "GULP", "NIKI", "ALPHA"]
    argParser.add_argument("-i", "--install", action="store_true", help="Install stuff")
    argParser.add_argument("-u", "--uninstall", action="store_true", help="Uninstall stuff")

    argParser.add_argument("-b", "--board", choices=boards, type=str.upper, default=boards[0], help=f"Board name, default: %(default)s")
    argParser.add_argument("-w", "--httpd", choices=["none", WWW_DIR, NGINX_CONF_DIR], type=str.lower, default=NGINX_CONF_DIR, help=f"How configure http server related stuff "+WWW_DIR+"..make links in /var/www/html, "+NGINX_CONF_DIR+"..make config), default: %(default)s")
    argParser.add_argument("-r", "--restart_services", action="store_true", help="Just restart running services")
    argParser.add_argument("-v", "--verbose", action="count", default=0, help="verbose output")
    argParser.add_argument("--version", action="version", version=f"%s" % __version__)

    args = argParser.parse_args()
    if args.install and args.uninstall:
        print("Options --install and --uninstall are mutually exclusive. Specify only one of them ")
        exit(1)

    if not args.install and not args.uninstall:
        print("Specify --install or --uninstall option")
        exit(1)

    def log(s):
        if args.verbose:
            print(s)

    PROJ_DIR=os.path.dirname(os.path.abspath(sys.modules[__name__].__file__))
    # system service
    # SYSTEMD_DIR=/lib/systemd/system
    # user service
    SYSTEMD_DIR=os.path.expanduser("~/.config/systemd/user")
    CONFIG_DIR=os.path.expanduser("~/.config/digie35")

    log("Project dir: %s" % PROJ_DIR)

    fs_services = {
        "hdmi-streamer": {"enable": True, },
        "digie35@": {"enable": True, "find_exe": "digie35_server", },
        "digie35-test@": {"enable": False, "find_exe": "digie35_test_server", },
    }

    disabled_services = [
        "gvfs-gphoto2-volume-monitor",
    ]

    disabled_gvfs = [
        "gvfsd-gphoto2",
    ]

    www_pages = {
        "digie35.html": ["index.html", ],
        "digie35_test.html": [],
        "qrcode.js": [],
        "dragsort.css": [],
        "dragsort.js": [],
        "tagify.css": [],
        "tagify.js": [],
        "tagify.polyfills.min.js": [],
    }
    www_images = {
        "digie35-scanner-96.png",
        "digie35-film-strip-96.png",
        "digie35-crop.svg",
        "digie35-crop-height.svg",
        "digie35-crop-width.svg",
    }

    desktop_prefix = "digie35-"
    desktop_apps = [
        "gui",
        "test",
        "liveview",
        "upgrade",
    ]

    desktop_icons_res = [16, 32, 96, ]
    desktop_icons = [
        "scanner",
        "film-strip",
        "film-roll-color",
        "film-roll-color2",
        "film-roll-bw",
    ]

    if (args.install):
        log("Installing...")
        for svc in disabled_services:
            log("Disabling service: %s" % svc)
            run(["systemctl", "--user", "stop", svc+".service"])

        for f in disabled_gvfs:
            log("Disabling gvfs service: %s" % f)
            run(["sudo", "killall", f], capture_output=True)
            run(["sudo", "chmod", "-x", "/usr/lib/gvfs/"+f])

        run(["mkdir", "-p", CONFIG_DIR])
        run(["mkdir", "-p", SYSTEMD_DIR])
        for svc in list(fs_services):
            f = PROJ_DIR+"/systemd/"+svc+".service"
            replace_exe = None
            if "find_exe" in fs_services[svc]:
                fn = fs_services[svc]["find_exe"]
                replace_exe = shutil.which(fn)
                if replace_exe == None:
                    log("Executable '%s' not found, skipping service '%s'" % (fn, svc))
                    continue
                else:
                    replace_exe = os.path.abspath(replace_exe)
                    log("Found executable '%s'" % replace_exe)
            f2 = SYSTEMD_DIR+"/"+svc+".service"
            log("Copying unit file '%s' to '%s'" % (f, f2))
            run(["cp", f, f2])
            if replace_exe != None:
                log("Patching unit file '%s'" % f2)
                run(["sed", "-i", "s~<<FILEPATH>>~"+replace_exe+"~g", f2])
            if args.restart_services:
                for board in boards:
                    svc2 = (svc + board) if "@" in svc else svc
                    proc = run(["systemctl", "--user", "is-active", svc2+".service"], capture_output=True)
                    log("Service status '%s': %s" % (svc2, proc.stdout.decode("utf-8")))
                    if proc.returncode == 0:
                        run(["systemctl", "--user", "daemon-reload"])   # to avoid warning
                        log("Restarting service '%s'" % (svc2))
                        run(["systemctl", "--user", "restart", svc2+".service"])
                    if not "@" in svc:
                        break
            else:
                if fs_services[svc]["enable"]:
                    svc2 = (svc + args.board) if "@" in svc else svc
                    log("Enabling service '%s'" % (svc2))
                    run(["systemctl", "--user", "enable", svc2+".service"])
                    run(["systemctl", "--user", "start", svc2+".service"])
        if args.httpd == WWW_DIR:
            for f in list(www_pages):
                tgt = www_pages[f]
                tgt.append(f)
                f = PROJ_DIR + "/html" + f
                for f2 in tgt:
                    f2 = WWW_DIR + "/" + f2
                    log("Linking WWW page '%s' to '%s'" % (f, f2))
                    run(["sudo", "rm", "-f", f2])
                    run(["sudo", "ln", "-s", f, f2])

            run(["sudo", "mkdir", "-p", WWW_DIR+"/images"])
            for f in www_images:
                f2 = WWW_DIR + "/images/" + f
                f = PROJ_DIR + "/images/" + f
                log("Linking image '%s' to '%s'" % (f, f2))
                run(["sudo", "rm", "-f", f2])
                run(["sudo", "ln", "-s", f, f2])
        elif args.httpd == NGINX_CONF_DIR:
            log("Installing nginx stuff")
            run(["sudo", "cp", PROJ_DIR + "/nginx/digie35.conf", NGINX_CONF_DIR + "/conf.d/"])
            sed_cmd = ["sudo", "sed", "-i", "s#\\$DIGIE35_DIRECTORY#" + PROJ_DIR + "#g", NGINX_CONF_DIR + "/conf.d/digie35.conf"]
            log(" ".join(sed_cmd))
            run(sed_cmd)
            run(["sudo", "rm", "-f", NGINX_CONF_DIR+"/sites-enabled/default"])
            run(["sudo", "nginx", "-s", "reload"])

        for f in desktop_icons:
            for res in desktop_icons_res:
                res = str(res)
                f2 = PROJ_DIR + "/images/" + desktop_prefix + f + "-" + res + ".png"
                name = desktop_prefix + f
                log("Registering icon '%s' as '%s'" % (f2, name))
                run(["xdg-icon-resource", "install", "--size", res,  f2, name])

        for f in desktop_apps:
            f = PROJ_DIR + "/desktop/" + desktop_prefix + f + ".desktop"
            log("Registering menu item '%s'" % (f))
            run(["xdg-desktop-menu", "install", "--mode", "user",  f])

    else:
        log("Uninstalling...")
        for svc in list(fs_services):
            if "@" in svc:
                for b in boards:
                    log("Stopping service: '%s'" % svc+b)
                    run(["systemctl", "--user", "stop", svc+b+".service"])
                    run(["systemctl", "--user", "disable", svc+b+".service"])
            else:
                log("Stopping service: '%s'" % svc)
                run(["systemctl", "--user", "stop", svc+".service"])
                run(["systemctl", "--user", "disable", svc+".service"])
            f2 = SYSTEMD_DIR+"/"+svc+".service"
            log("Removing unit file '%s'" % f2)
            run(["rm", f2])

        if args.httpd == WWW_DIR:
            for f in list(www_pages):
                tgt = www_pages[f]
                tgt.append(f)
                for f2 in tgt:
                    f2 = WWW_DIR + "/" + f2
                    log("Removing WWW link '%s'" % f2 )
                    run(["sudo", "rm", f2])

            for f in www_images:
                f = WWW_DIR + "/images/" + f
                log("Removing WWW link '%s'" % f )
                run(["sudo", "rm", f])
        elif args.httpd == NGINX_CONF_DIR:
            log("Removing nginx stuff")
            run(["sudo", "rm", NGINX_CONF_DIR+"/conf.d/digie35.conf"])
            run(["sudo", "ln", "-s", NGINX_CONF_DIR+"/sites-available/default", NGINX_CONF_DIR+"/sites-enabled/default"])
            run(["sudo", "nginx", "-s", "reload"])

        for f in desktop_apps:
            f = desktop_prefix + f + ".desktop"
            log("Unregistering menu item '%s'" % (f))
            run(["xdg-desktop-menu", "uninstall", "--mode", "user", f])

        for f in desktop_icons:
            for res in desktop_icons_res:
                res = str(res)
                name = desktop_prefix + f
                log("Unregistering icon '%s'" % (name))
                run(["xdg-icon-resource", "uninstall", "--size", res,  name])

    log("Reloading systemd")
    run(["systemctl", "--user", "daemon-reload"])


if __name__ == "__main__":
   main()

