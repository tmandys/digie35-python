v0.6 (2024-xx-xx)
=================

Features
--------
  - bookworm support at RPI5

Fixes
-----
  - select camera by usbid or name as usbid increases value
  - fix stepper board v 1.03 enable signal

v0.5 (2024-06-19)
=================

Features
--------
  - board 1.03 support
  - plugin detection on server side and client notification


v0.4 (2024-05-26)
=================

Fixes
-----
  * autoincrement film_id will reuse next empty film_id
  * swapped sense of reverse, i.e. normal direction is right to left
  * eject will force to move even film is not detected to refresh sensors states

Features
--------
  * hot key fo backlight
  * changelog introduced
  * do not capture when backlight is off
  * consider only files larger then 100kB as images when listing directories to avoid potential metadata, e.g. Lightroom .xmp)

v0.3 (2024-05-20)
=================

Features
--------
  * upgrade script
  * watch_*.py scripts
  * gpiozero support (required for RPI 6)
