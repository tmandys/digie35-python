Digie35 Control
===============

digie35 uses RPi harware which must be enabled via editing `/boot/config.txt` and reboot.

DEVEL board
-----------
requires I2C enabled

    dtparam=i2c_arm=on

May be done from GUI via `raspi-config` as well

When GPIO3 is overriden e.g. by sleep listener then set SCL function

    raspi-gpio set 3 a0

NIKON+HEAD board
----------------
requires hardware PWM on GPIO12/13. It is in conflict with audio jack

    dtoverlay=pwm2chan,pin=12,func=4,pin2=13,func2=4
plus
    sudo pip3 install rpi-hardware-pwm


NIKON board
-----------

to enable activity led

    dtoverlay=act-led,gpio=14

HEAD board
----------
When GPIO3 is overriden e.g. by sleep listener then set SCL function

    raspi-gpio set 3 a0

Enable RTC support for MCP7940x at 0x6f I2C address

    i2cset -y1 1 0x6f 0x00 0x80

and check if clock is running

    rtc_read.py

Add module to `/boot/config.txt`

    dtoverlay=i2c-rtc,mcp7940x

Reboot and check if UU appears indicating kernel support for RTC

    i2cdetect -y 1
    sudo hwclock -r

to enable activity led

    dtoverlay=act-led,gpio=26


Development
-----------
To get rid of package_name.module_name or .module_name import needed when installed vs.
running in repository install package locally

    python -m pip install -e .

Check video formats provided by HDMI grabber

    ffmpeg -f v4l2 -list_formats all -i /dev/video0
      [video4linux2,v4l2 @ 0xf96cd0] Compressed: mjpeg :
      Motion-JPEG : 1920x1080 1600x1200 1360x768 1280x1024 1280x960 1280x720 1024x768 800x600 720x576 720x480 640x480
      [video4linux2,v4l2 @ 0xf96cd0] Raw: yuyv422 :YUYV 4:2:2 :
      1920x1080 1600x1200 1360x768 1280x1024 1280x960 1280x720 1024x768 800x600 720x576 720x480 640x480

Installation
------------

Installing to a virtual environment

    mkdir ~/digie35
    cd ~/digie35
    python3 -m venv env

    source env/bin/activate

    digie35_install -i

It does automatically copying systemd unit files as user services,
disables conflict ghoto2 stuff, created menu entries and symlinks files
to http server.

I.e. following steps required in case of manual installation:

Copy `digie35/systemd/*.service` to `~/.config/systemd/user` and fix ExeStart,
symlink `digie35/*.html` to `/var/www/html` HTTP server (nginx) directory,
`digie35/desktop/*.desktop` to `~/.local/share/applications`, make `~/.config/digie35` dir.

Disable gphoto2 volume monitor service to leave USB connection to camera

    systemctl --user stop gvfs-gphoto2-volume-monitor.service
    systemctl --user mask gvfs-gphoto2-volume-monitor.service

Stop running gvfsd-gphoto2 daemon and prevent auto start

    sudo killall gvfsd-gphoto2
    sudo chmod -x /usr/lib/gvfs/gvfsd-gphoto2

Enable hdmi streamer

    systemctl --user enable hdmi-streamer.service
    systemctl --user start hdmi-streamer.service

Enable and start scanner service for particular board

    systemctl --user enable digie35@HEAD.service
    systemctl --user start digie35@HEAD.service

Upgrade
-------

Upgrade script `digie35_upgrade` will look in repository and if newer package is found then install it.

Issues
------

- nginx cannot display page and returns "403 Forbidden"

nging requires X right to whole tree of parent directories of particular file on linked location. Check it with

    namei -l /var/www/html/index.html
    f: /var/www/html/index.html
    drwxr-xr-x root     root     /
    drwxr-xr-x root     root     var
    drwxr-xr-x www-data www-data www
    drwxr-xr-x root     root     html
    lrwxrwxrwx root     root     index.html -> /home/pi/.local/lib/python3.9/site-packages/digie35/digie35.html
    drwxr-xr-x root     root       /
    drwxr-xr-x root     root       home
    drwxr-xr-x pi       pi         pi
    drwxr-xr-x pi       pi         .local
    drwxr-xr-x pi       pi         lib
    drwxr-xr-x pi       pi         python3.9
    drwx------ pi       pi         site-packages     <------------
    drwxr-xr-x pi       pi         digie35
    -rw-r--r-- pi       pi         digie35.html

In this case it is `/home/pi/.local/lib/python3.9/site-packages/`

    chmod a+x /home/pi/.local/lib/python3.9/site-packages/

- Sony A7 cameras when using USB preview, i.e. since A7 II

There is a bug in gphoto2 library which causes USB failure. Camera must be restarted to connect again.
`gphoto2-2.5.1.1-cp311-cp311-linux_aarch64.whl` is provided in digie35 repo to fix it.

- Random camera communication failure (I/O error, bad params)

Seems USB 3.0 issue caused by a low quality cable. Replace cable

- Extarnal hardisk is dismounted randomly

Check power consumption of USB devices, e.g. when powering camera from USB. Check dmesg where "overcurrent" log entry may appear.
Use powered hub for high current USB devices.

Usage
-----

There are running services providing API via websockets.
For cameras supporting HDMI live view plug in HDMI Video Capture USB stick. Frint-end user interface is implemented in
digie35.html which is to be opened in web browser at `http://localhost/` address (when nginx http server is running)
or alternatively as local file `file://<path>/digie35.html`. Javascript support is mandatory.
_Midori_ lightweight browser not stressing RPI as much e.g. _Chromium_. But it does not show video stream correctly and is not currently
available in _Bookworm_ repository to download.
Captured photos are saved on (RPI) filesystem and intended location is SSD disk (or USB stick) plugged in USB. Alternatively
a network disk is also reasonable option. Internal SD card is bad choice for storage.

Captured files can be accessed over network Samba prototol. Samba user is added using

    smbpasswd -a pi
    
