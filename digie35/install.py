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

from subprocess import run as subprocess_run
import argparse
import os
import sys
import locale
import shutil
import shlex
import stat

def run(command, *, allowed_codes=(0,), **kwargs):
    """Stop on failed commands; callers explicitly allow expected nonzero results."""
    try:
        result = subprocess_run(command, **kwargs)
    except OSError as exc:
        sys.exit(f"Cannot run {shlex.join(command)}: {exc}")
    if result.returncode not in allowed_codes:
        if kwargs.get("capture_output") and result.stderr:
            print(result.stderr.decode("utf-8", errors="replace"), file=sys.stderr)
        sys.exit(f"Command failed ({result.returncode}): {shlex.join(command)}")
    return result

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
        sys.exit(1)

    if not args.install and not args.uninstall:
        print("Specify --install or --uninstall option")
        sys.exit(1)

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

    nginx_configs = [
        "digie35.conf",
        "ustreamer.conf",
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

    www_sounds = {
        "error.mp3",
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
        run(["mkdir", "-p", CONFIG_DIR])
        for svc in disabled_services:
            log("Disabling service: %s" % svc)
            run(["systemctl", "--user", "stop", svc+".service"], allowed_codes=(0, 5))  # unit may not exist

        for f in disabled_gvfs:
            path = "/usr/lib/gvfs/" + f
            if not os.path.exists(path):
                continue
            log("Disabling gvfs service: %s" % f)
            backup = os.path.join(CONFIG_DIR, f + ".mode")
            if not os.path.exists(backup):
                # Preserve the first saved mode across repeated installations.
                with open(backup, "x", encoding="ascii") as stream:
                    stream.write(format(stat.S_IMODE(os.stat(path).st_mode), "o"))
            run(["sudo", "killall", f], allowed_codes=(0, 1))  # no matching process
            run(["sudo", "chmod", "a-x", path])

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
                    proc = run(["systemctl", "--user", "is-active", svc2+".service"], capture_output=True, allowed_codes=(0, 3, 4))
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
                    run(["systemctl", "--user", "daemon-reload"])
                    run(["systemctl", "--user", "enable", svc2+".service"])
                    run(["systemctl", "--user", "start", svc2+".service"])
        if args.httpd == WWW_DIR:
            for f in list(www_pages):
                tgt = www_pages[f]
                tgt.append(f)
                f = PROJ_DIR + "/html/" + f
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
            run(["sudo", "mkdir", "-p", WWW_DIR+"/sounds"])
            for f in www_sounds:
                f2 = WWW_DIR + "/sounds/" + f
                f = PROJ_DIR + "/html/sounds/" + f
                log("Linking sound '%s' to '%s'" % (f, f2))
                run(["sudo", "rm", "-f", f2])
                run(["sudo", "ln", "-s", f, f2])
        elif args.httpd == NGINX_CONF_DIR:
            log("Installing nginx stuff")
            for cfg in nginx_configs:
                run(["sudo", "cp", PROJ_DIR + "/nginx/" + cfg, NGINX_CONF_DIR + "/conf.d/"])
                sed_cmd = ["sudo", "sed", "-i", "s#\\$DIGIE35_DIRECTORY#" + PROJ_DIR + "#g", NGINX_CONF_DIR + "/conf.d/" + cfg]
                log(" ".join(sed_cmd))
                run(sed_cmd)
            run(["sudo", "rm", "-f", NGINX_CONF_DIR+"/sites-enabled/default"])
            run(["sudo", "nginx", "-t"])
            run(["sudo", "nginx", "-s", "reload"])
            if args.restart_services:
                log("Restarting service 'nginx'")
                run(["sudo", "systemctl", "try-restart", "nginx.service"])

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
        for f in disabled_gvfs:
            backup = os.path.join(CONFIG_DIR, f + ".mode")
            path = "/usr/lib/gvfs/" + f
            if os.path.exists(backup):
                with open(backup, encoding="ascii") as stream:
                    mode = int(stream.read().strip(), 8)
                if not 0 <= mode <= 0o7777:
                    sys.exit(f"Invalid saved permissions: {backup}")
                if os.path.exists(path):
                    run(["sudo", "chmod", format(mode, "o"), path])
                    os.remove(backup)
            elif os.path.exists(path):
                print(f"No saved permissions for {path}; leaving its mode unchanged.", file=sys.stderr)
        for svc in list(fs_services):
            if "@" in svc:
                for b in boards:
                    log("Stopping service: '%s'" % svc+b)
                    run(["systemctl", "--user", "stop", svc+b+".service"], allowed_codes=(0, 5))
                    run(["systemctl", "--user", "disable", svc+b+".service"], allowed_codes=(0, 5))
            else:
                log("Stopping service: '%s'" % svc)
                run(["systemctl", "--user", "stop", svc+".service"], allowed_codes=(0, 5))
                run(["systemctl", "--user", "disable", svc+".service"], allowed_codes=(0, 5))
            f2 = SYSTEMD_DIR+"/"+svc+".service"
            log("Removing unit file '%s'" % f2)
            run(["rm", "-f", f2])

        if args.httpd == WWW_DIR:
            for f in list(www_pages):
                tgt = www_pages[f]
                tgt.append(f)
                for f2 in tgt:
                    f2 = WWW_DIR + "/" + f2
                    log("Removing WWW link '%s'" % f2 )
                    run(["sudo", "rm", "-f", f2])

            for f in www_images:
                f = WWW_DIR + "/images/" + f
                log("Removing WWW link '%s'" % f )
                run(["sudo", "rm", "-f", f])
            for f in www_sounds:
                f = WWW_DIR + "/sounds/" + f
                log("Removing WWW link '%s'" % f )
                run(["sudo", "rm", "-f", f])
        elif args.httpd == NGINX_CONF_DIR:
            log("Removing nginx stuff")
            for cfg in nginx_configs:
                run(["sudo", "rm", "-f", NGINX_CONF_DIR+"/conf.d/"+cfg])
            if not os.path.lexists(NGINX_CONF_DIR+"/sites-enabled/default"):
                run(["sudo", "ln", "-s", NGINX_CONF_DIR+"/sites-available/default", NGINX_CONF_DIR+"/sites-enabled/default"])
            run(["sudo", "nginx", "-t"])
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
