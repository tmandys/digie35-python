Packaged backlight response profiles belong here as individual JSON files.
Only measured profiles should be shipped; no synthetic default is provided.
Schema version 1 uses the same format as user profiles in server storage.
Required fields: name, schema_version, units (preview_rgb_per_channel_gain),
channels, matrix (3 rows, one column
per channel). Calibration also records baseline, samples, camera and preview
settings. New calibrations also contain light (server-read EEPROM identity),
mode and sampling (full_frame_mean and source dimensions). Serial numbers are
strings or null, never JavaScript numbers. Files are read-only in the UI. Use portable identifier filenames
(letters, digits, underscore, hyphen); the display name can contain Unicode.
