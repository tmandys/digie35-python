# Backlight Uniformity Analysis

Run from the repository root using the existing local environment:

```powershell
.\.venv\Scripts\python.exe -m digie35.backlight_analyzer "C:/Users/tmand/Pictures/2026_09_28/IMG_0007-LGP+DIFF-mat_d-RGB.CR3" --output target-reports/backlight-rgb
```

Dependencies are the same as `requirements-target-analysis.txt`. No additional
packages or Raspberry Pi hardware are required. The source files are read only.
The output directory must be new and contains `report.html`, `report.json` and
`grid.csv`. Open the HTML in a browser to view or print the report.

## Measurement

The analyzer reads native Bayer CFA data through LibRaw. It subtracts each CFA
channel's black level and divides by its white-minus-black range. Camera-specific
white levels are preferred when available. There is no demosaic, white balance,
gamma curve, brightness adjustment or lens correction. Both green CFA planes
contribute to the green-channel cell medians. Only 2x2 RGB Bayer layouts are
currently supported; JPEGs are not measurement inputs.

Default coverage is the complete RAW visible raster, using 48x32 spatial cells.
Each cell contains a median signal for R, G and B. Statistics describe these cell
medians, not pixel noise or the worst dust spot. Native sample clipping and low
signal are checked separately. A signal below 1% of the available RAW range is
flagged; this is a heuristic, not a camera noise calibration.

The report starts with a **Combined RGB signal** map and center-strip profiles:
the arithmetic mean of the R/G/B tile medians before spatial normalization or
white balance. This provides an overall signal view for white LEDs and RGB
mixtures, but is not calibrated photometric luminance. It retains the relative
channel strengths; channels are not individually normalized to their means
before combining. Weak channels suppress combined statistics, and any source
channel clipping flags remain visible. The combined grid is also exported to CSV
and JSON. Separate channel and color-ratio maps remain necessary because an
overall signal map can hide color variation.

The report includes CV, P5/P95, robust span, tile extrema, corner/center ratios,
relative maps, center-strip profiles and R/G and B/G spatial ratio maps. Color
ratios are omitted when either channel is clipped or has low-signal flags.
Sensor channels do not directly identify which physical LEDs were active; names
such as RGB, 3000K and 5000K are retained in the source filename without assuming
an individual LED state. There is no calibrated luminance or CCT measurement.

## Region and Display Scale

```powershell
.\.venv\Scripts\python.exe -m digie35.backlight_analyzer "image.CR3" --output target-reports/field-crop --roi 0.1 0.1 0.9 0.9 --columns 48 --rows 32 --map-limit 20
```

ROI coordinates are normalized left, top, right, bottom. Actual pixel boundaries
are aligned to complete Bayer cells and recorded in the report. Choose the usable
film field explicitly when borders, a frame or unilluminated areas are present.
Use the same ROI and grid for comparisons. There is no automatic field detection.

Maps show percent deviation from each map's mean with a fixed symmetric scale,
default +/-20%. Values beyond the scale saturate in color; statistics remain
unclipped. Horizontal and vertical profiles use the central two rows/columns.
EXIF rotation is not applied. Keep camera orientation fixed between captures.

## Interpretation

This measures the complete imaging setup, including lens vignetting, sensor,
diffuser and holder. It cannot isolate panel uniformity from a single photograph.
The two green CFA planes are not separately calibrated. Camera RAW processing
performed before storage cannot be undone by this program.

For comparing spatial uniformity, different exposure times are acceptable if
signals are sufficiently above noise and below saturation. Comparing mean signal
as intensity requires exposure and spectral calibration; this tool does not
perform it. An RGB mix must not be interpreted as separate R/G/B LED exposures.

Capture a blank field in the working configuration with fixed aperture, ISO,
focus and camera position. Avoid clipping any relevant channel. Use exposure
times long enough to average LED PWM. Record LED settings separately.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_backlight_analyzer -v
```
