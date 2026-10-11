Digie35 Control
===============

digie35 uses RPi harware which must be enabled via editing `/boot/firmware/config.txt` and reboot.

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


NIKON board + GULP v 1.00
-------------------------

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

Add module to `/boot/firmware/config.txt`

    dtoverlay=i2c-rtc,mcp7940x

Reboot and check if UU appears indicating kernel support for RTC

    i2cdetect -y 1
    sudo hwclock -r

to enable activity led

    dtoverlay=act-led,gpio=26

To use TMC22xx in UART mode enable UART (without serial console) and disable bluetooth

    enable_uart = 1
    dtoverlay = disable-bt

    sudo systemctl disable --now hciuart.service

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

Init and update submodules

    git submodule update --init --recursive
    git submodule update --recursive

Use gdb to debug, e.g.:

    gdb --args python ./digie35_server.py -vvvv
    > run

### Frontend state tests

The frontend regression tests require Node.js (tested with v24.19.0), available
as `node` on your PATH. No `npm install`, Python environment, running server,
browser, camera, or Raspberry Pi hardware is needed. They can run on a regular
Windows, Linux, or macOS computer.

From the repository root, run:

```sh
node --version
node tests/frontend_state_review.cjs
```

The script reads the current `digie35/html/digie35.html` and executes its inline
JavaScript with simulated DOM elements, WebSocket messages, and timers. It checks
scenarios such as Stop followed by a late analysis response, manual movement,
automatic capture sequences, and download errors. It does not start or execute
the Python backend: server messages are constructed by the tests.

Each scenario prints `PASS` or `FAIL`, followed by a summary. A successful run
ends with `0 failed` and exit code 0; failed assertions produce exit code 1.
Currently the suite contains 27 scenarios. To test a different copy of the HTML,
pass its path as an optional argument:

```sh
node tests/frontend_state_review.cjs /path/to/digie35.html
```

These tests do not modify the HTML or control any hardware. They verify selected
event sequences, not the complete browser/backend integration or physical timing;
end-to-end testing on the Raspberry Pi is still needed.

### TMC2208 UART diagnostics

The standalone UART tool checks TX/RX loopback, register reads and a verified
write of unchanged GCONF. It does not configure motor current or replace STEP/DIR.
See [hardware preparation, commands and tests](docs/tmc2208-uart.md).

Installation
------------

### Local server storage

`digie35_server --storage-directory PATH` sets the directory for persistent server
data, separate from the photo/project directory selected with `--directory`.
The default is `$XDG_DATA_HOME/digie35` when `XDG_DATA_HOME` is absolute and
nonempty, otherwise `~/.local/share/digie35`. Paths support `~` and environment
variables and are resolved to absolute paths. Relative paths use the working
directory of the server process.

The server creates the directory and checks write access before starting its
listeners. The installed user service uses the home directory of the account
running that service. To override the location, add `--storage-directory PATH`
to its `ExecStart` command.

The `digie35.storage.LocalStorage` API provides `save(category, name, data)`,
`load(category, name)` and `list(category)` for JSON records. Backlight response
profiles reside in `color_profiles/<profile_id>.json` under the configured root.
Writes atomically replace each complete JSON file. Missing records and invalid
JSON raise errors rather than returning an empty profile.

Backlight settings contains the profile selector and **New calibration** dialog.
Remove the film, fill the entire preview with the illuminated diffuser, lock
camera exposure/ISO/WB before starting. Analyze is enabled automatically and its
original state is restored after success, failure or cancellation. Precise focus on a
uniform diffuser is unnecessary; disable autofocus. The eyedropper and its sample
size are independent of calibration, which measures the central 90% of source-snapshot
width and height (5% is ignored at each edge for averaging and clipping checks).
The darkest and brightest 10% of values in each RGB channel are excluded
to reduce dust and reflection effects. Clipping is checked on all pixels in that region before
trimming. Histograms and strip reads limit temporary memory.
Calibration automatically selects channels from the connected hardware's
capabilities: RGBAW first, otherwise RGB with white when available, RGB alone,
or white alone. The dialog shows the light identity and selected channels;
the server determines and verifies the selection. RGBAW measures amber and
white independently. Each channel is measured at 80% and 120% of its starting
gain, with fixed exposure and white temperature. A different mode starts with unit gains; disabled channels
are also initialized to unit gain. The original mode and levels are restored.
Calibration uses the Preview settling delay, rejects dark/clipped
samples, waits for three stable new snapshots, and verifies the original RGB.
The resulting matrix is local to those settings and describes decoded preview
RGB per unit of channel gain, not linear RAW values or a full-range PWM model.
Automatic WB correction is not implemented by selecting a profile yet.

LED gain presets are separate from response profiles. The light-mode dropdown
keeps the basic modes first, followed by nonempty preset groups for RGB,
RGB+White and RGBAW, and actions to save, update or delete presets. Only presets
matching the connected light identity and supported mode are listed. Presets
store channel gains and enable switches, never EV or white temperature, in
individual JSON files under `led_presets/` in server storage. Duplicate names
are rejected within the same light and mode. Without a serial number, compatible
units with the same adapter identity cannot be distinguished.

Selecting a preset applies its mode and gains while retaining current EV. The
panel shows its name, with `*` after manual gain/switch edits. OFF retains the
last active mode, selected preset and working channel values, including unsaved
edits. These values are persisted per light in browser settings; refreshing an
OFF session does not turn the light on. On connection with other clients, live
server state takes precedence. Calibration's temporary changes are not saved
over the preset's working state.

PCA9634 light adapters (including the manual 120 light box) report logical
channel PWM in `backlight.pwm`: requested value, actual value, maximum,
`clipped` (request above maximum), and `at_limit` (output at maximum).
`at_min` identifies a positive request that quantizes to zero PWM; intentionally
disabled channels do not trigger it. The UI reserves a fixed warning-icon slot
beside each gain control; tooltips show MIN/MAX/CLIP and numerical PWM values.
White temperature mixing happens
after this logical PWM limit. Older drivers without this reporting omit the
field. Calibration finds LED exposure in 0.5 EV steps within -2.5 to +2.5 EV,
using only settings with PWM headroom for the 0.8x/1.2x probes on supported
adapters. It targets a brightest mean RGB channel of 80–180 in preview; at a safe
EV boundary it may accept a dimmer valid measurement. If no valid measurement
is possible, it reports the limit rather than changing the camera. The chosen
LED exposure stays fixed throughout the channel measurements and is saved in
the profile; original lighting is restored afterwards. The search is bounded
and never revisits an EV setting. Lowering camera exposure cannot resolve an LED PWM limit.

New calibrations cover the whole lightbox, regardless of the currently selected
LED mode. The server starts from unit gains and discovers visible channels from
capabilities. Each channel is measured alone with all other channels off; on
tunable-white RGBAW hardware the `white` and `amber` outputs are measured separately
and labelled White 5000 K and White 3000 K. Isolated gains are adjusted within
PWM headroom to obtain a usable signal while keeping LED EV fixed. Dark cross
channels are expected during isolated measurements and do not invalidate them.

The profile stores `isolated_samples` and `isolated_matrix`, including the actual
gain and settings of each measurement. It also measures the local response in
the reference mixture, retained in `matrix` for the WB controller. These are
separate measurements: nonlinear preview RGB must not be treated as an additive
sum of the isolated channels. Reference-mixture drift is checked at the end.
Camera exposure must remain fixed for the entire run (manual or reliable AE
lock). Camera WB Kelvin and shift are entered in the dialog, remembered in
browser settings and stored as user-declared profile metadata; camera settings
are not read or changed automatically. Existing profiles remain readable.

User profile names are checked before calibration and again at save time,
ignoring letter case and surrounding whitespace. A profile is a portable JSON
file with its display name and measurements; copying a valid file with a unique
identifier filename into `color_profiles` makes it available on the next list
refresh. The server merges these with read-only profiles packaged under
`digie35/color_profiles`. No unmeasured default profile is supplied. The UI can
delete only user profiles, and remembers the selected profile on that browser.

Each new profile records the connected light's EEPROM name, adapter/board IDs,
adapter class, hardware version and serial number. Identity is read by the
server from the memory selected by the actual light adapter (including integrated
120-film/lightbox adapters), and attached by the server when saving a completed
calibration. Unassigned serial numbers are null; assigned numbers are strings to
preserve their full 64-bit precision in browsers. Changing the connected light
during calibration invalidates the session; old settings are not applied to a
replacement light. Profiles without EEPROM hardware fall back to the driver
class name and an unknown serial number.

The server owns a single calibration session and restores its original light
on completion, cancellation, disconnection or after 120 seconds without a step.
Other hardware-changing commands are blocked during calibration; Stop cancels
it. Snapshot timestamps identify buffer arrivals, not sensor exposure times:
the settling delay still needs to match the camera/preview path. Sources without
timestamp headers use separate snapshot requests as the fallback.

LED white balance is started with **WB** beside the RGB readout in Analyze.
Select a camera, an RGB/RGB+White/RGBAW mode,
a matching calibration profile in Backlight settings, and click a neutral
reference area in the preview (for negative mask compensation, use clear film
base). WB automatically enables disabled RGB channels using their current slider
gains; cancellation restores their original switches and gains. Camera exposure
and camera WB must remain fixed. Sampling uses the
configured neighborhood of the selected point in the source snapshot, before
display inversion, with the same trimmed mean as the RGB readout.

The server uses the measured response profile to propose bounded gain changes across all enabled channels
(including white and amber); the browser waits for the configured settling delay and three stable
new snapshots after each change. Disabled white/amber outputs stay off; EV remains unchanged. The solver respects
individual PWM limits and may reduce overall brightness to reach neutral RGB
when a channel cannot increase further. White reductions are limited to 35%
per step, other reductions to 20%, and increases to 15%.
WB stops at neutral RGB (spread at most 2 levels or 2%), or after 16 corrections.
Gain/PWM limits, invalid samples and divergence terminate the run. Cancel WB,
Stop, disconnect and inactivity restore the original light; only a successfully
measured correction is kept. Capture, calibration and other hardware changes
are blocked by the server during WB. The resulting gains can be saved as an LED
preset. Profiles are local response estimates: a strongly colored film or a
different camera rendering may prevent convergence.

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

- General Segmentation Fault or similar error

To get more info in terminal use

  export PYTHONFAULTHANDLER=1


- nginx cannot display page and returns "403 Forbidden"

nginx requires X right to whole tree of parent directories of particular file on linked location. Check it with

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

- digie35_server complains that GPIO is busy

Check if `/boot/firmware/config.txt` corresponds to board. E.g. GPIO26 is busy when using NIKI board with config.txt from HEAD board where GPIO26 is used for RPI LED status indication. Also `pintest -p <pin#>` or `gpioinfo` may help to prove suspicion.

- Unable install local Python local package bacause of "error: externally-managed-environment"

  sudo rm  /usr/lib/python3.11/EXTERNALLY-MANAGED

- RPI5 power button is handled by system

KEY_POWER event can be monitored by `evtest`. It is handled by lxde and firewire which executes `/bin/pwrkey`
and opens GUI window to select Shutdown or Restart. This function must be disabled because it is handled
by `digie35_server`. So it executes fake script to prevent `pwrkey` execution.

- OS started from SSD connected to NVMe/PCI port on RPI5

Add PCI support to `/boot/firmware/config.txt`

[all]
dtparam=pciex1=on
# dtparam=pciex1_gen=3

LED activity is triggered by specific action. To change from mmc0 (i.e. SD card) to e.g. default-on use:

dtparam=act_led_trigger=default-on

Current settings is available (and changeable) via

  cat /sys/class/leds/ACT/trigger
  echo <opt> | sudo tee /sys/class/leds/ACT/trigger

Check boot order via `rpi-eeprom-config` if PCI is mentioned. Parameter is evaluated right to left.
1..SD card, 6..PCI, 4..USB, f..stop

So good value is e.g.:

  BOOT_ORDER=0xf461

If not then modify via `sudo rpi-eeprom-config -e`, save and reboot. Note `rpi-eeprom-config` won't report
updated value till reboot.

- RPI5 USB-C PD

To avoid warnings because powered via internal PSU over GPIO and not via USB-C
where negotiates PD params then add option to rpi-eeprom-config

  PSU_MAX_CURRENT=4000

Usage
-----

There are running services providing API via websockets.
For cameras supporting HDMI live view plug in HDMI Video Capture USB stick. Frint-end user interface is implemented in
digie35.html which is to be opened in web browser at `http://localhost/` address (when nginx http server is running)
or alternatively as local file `file://<path>/digie35.html`. Javascript support is mandatory.
_Midori_ lightweight browser not stressing RPI as much e.g. _Chromium_. But it does not show video stream correctly
and is not currently available in _Bookworm_ repository to download.
Captured photos are saved on (RPI) filesystem and intended location is SSD disk (or USB stick) plugged in USB.
Alternatively a network disk is also reasonable option. Internal SD card is bad choice for storage.

Captured files can be accessed over network Samba prototol from Windows or Mac OS. Samba user is added using

    smbpasswd -a pi

Digie35 server log is available via websocket in browser console or CLI `digie35_log` util.
