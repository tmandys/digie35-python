# Offline Target Analysis

The standalone `digie35.target_analyzer` module does not import the server or
Raspberry Pi hardware modules. It leaves `digie35image.py` and the live focus
score unchanged.

## Local Windows Environment

A `.venv` environment (Python 3.12) is available in the project root. No environment
activation or PowerShell ExecutionPolicy change is required:

```powershell
.\.venv\Scripts\python.exe -m digie35.target_analyzer digie35/test_targets/capt_A7_00001_20261020214738.JPG --output target-reports/test-01
```

You can also supply an original RAW file, such as Sony ARW:

```powershell
.\.venv\Scripts\python.exe -m digie35.target_analyzer E:/Photos/target.ARW --output target-reports/raw-01
```

The output directory must not exist. The program does not overwrite existing
reports. Open `report.html` in a browser to view, print or save it as PDF.
The output also includes `map.png`, `report.json` and `measurements.csv`.
Hover over the map to display a magnifier above the pointer (or below when space
is limited). The selector offers 4x displayed size, 1:1 annotated-map pixels,
and Off. The 1:1 option does not show original RAW pixels. The magnifier works
offline and is hidden when printing.

Square labels use four lines: location, reciprocal edge width (px^-1),
signed percentage deviation from the arithmetic mean of fully valid squares,
and `F` followed by the Laplacian focus score.
This value is not the Laplacian focus score. Borders are neutral gray within
plus/minus 5% of the mean, then gradually red below or green above the mean,
with full saturation at plus/minus 20%. Invalid squares are amber. These fixed
display thresholds do not represent measurement uncertainty or pass/fail limits.
JSON and CSV also include `sharpness_deviation_percent` for each square.
The HTML table lists sharpness and signed deviation as separate columns.
The report includes an equivalent command reconstructed from its settings, with
absolute input paths and the selected reference frame. Change `--output` to a
new directory before rerunning. This command is also recorded in JSON; it is
not a historical log of the shell invocation.

The additional focus score uses the online formula: the maximum of the R, G
and B Laplacian variances (`cv2.Laplacian(channel, cv2.CV_64F).var()`). The
96-by-96 source-pixel ROI is centered on the detected square, shifted inward
at image boundaries and reduced only if the image is smaller. Square interiors
may be flat: these scores can primarily reflect texture/noise rather than focus.
For RAW files the input is the 8-bit display RGB (power 1/2.2, unity WB, no auto
brightness), not the linear green channel used for edge widths. This does not
reproduce the camera JPEG rendering, so absolute scores are not interchangeable
with live preview. JSON includes RGB scores and ROI bounds; HTML and CSV include
the maximum and selected channel. Map colors still represent edge sharpness.

To recreate the environment on another computer with Python 3.10+ installed:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-target-analysis.txt
```

The current environment was created using the Python runtime bundled with Codex.
If that installation moves, recreate `.venv` using a standard Python installation.
Virtual environments are not portable by copying them to another computer.
Do not install the entire `setup.py` on Windows: it also includes Raspberry Pi
hardware dependencies.

## Supported Target and Measurements

- A regular grid of dark squares rotated by approximately 5 degrees; the default
  grid is 9 columns by 7 rows.
- The new target has 59 measurement squares and four larger markers. Markers are
  filtered by size; their codes are not decoded yet.
- For example, `--columns 9 --rows 9` selects a square grid for another format.
- The middle portions of all four edges are measured at the original resolution.
  Only square detection uses a downscaled image. The report lists transition
  widths separately for the X and Y directions.
- Diagnostic sharpness is the reciprocal of the mean 10-90% transition width in
  pixels. Higher values mean sharper transitions. This is not the original
  Laplacian focus score, lp/mm or MTF50.
- A projective grid determines the pattern center and deviations of square
  positions from the common model. The pattern center offset from the image
  center is not an optical-axis offset.
- RAW conversion uses rawpy/LibRaw to produce linear camera RGB, with no automatic
  brightness, unity white balance and simple linear demosaicing. The green channel
  is measured. This is still a demosaiced image, not the unprocessed CFA array.
- JPEG/PNG and 8-bit RGB/grayscale TIFF images are measured without assuming a
  particular gamma curve. Their results are not numerically interchangeable with
  RAW results. EXIF orientation is not applied.

## Source Artwork Reference

A raster source strip can be supplied as an optional geometric reference:

```powershell
.\.venv\Scripts\python.exe -m digie35.target_analyzer digie35/test_targets/capt_A7_00001_20261020214738.JPG --reference digie35/test_targets/terc.tif --reference-frame 1 --output target-reports/reference-test
```

The source artwork must contain rectangular frames enclosing the regular grid.
The analyzer extracts frames from left to right and uses the selected frame's
actual square centers to fit the photographed geometry. The supplied `terc.tif`
contains five frames; select 1 through 5. It is a reference strip, not five
measurement images. The captured image must contain one target in the same
orientation as the selected reference. Marker codes are not decoded or used to
identify which repeated frame was photographed.

The JSON records source SHA-256, frame bounds, normalized square positions, DPI
and reference-fit residuals. Coordinates are normalized within each frame, so
reference geometry does not depend on physical target dimensions. DPI-derived
millimeters are explicitly nominal and do not calibrate the printed target.
Source rasterization is not compensated in sharpness measurements. For precise
optical tests, high-resolution/vector artwork and physical calibration are still
needed. A photographed film strip containing several targets is not supported.

## Perspective and Rotation

The annotated `map.png` includes a cyan fitted quadrilateral, dimension lines in
original-image pixels, and clockwise-positive rotation angles. The outline is
not exaggerated. With source artwork it represents the inferred source frame;
without artwork it connects the fitted outer grid centers, not the target border.
No border pixels are measured directly.

Width change is `100 * (bottom - top) / mean(bottom, top)`; height change uses
`right - left`. Rotation is the mean of the top and bottom side angles relative
to horizontal. Individual vertical side angles are relative to vertical.
These are image-plane measurements, not physical tilt angles or millimeters.

The HTML and schema-version-2 JSON include affine and projective fit RMS plus
sensitivity ranges obtained by omitting each row and each column in turn.
These ranges are not statistical confidence intervals. A range crossing zero
or negligible improvement over the affine fit weakens evidence for convergence.
Lens distortion, target manufacturing errors and detection errors remain mixed
with perspective. Reference and grid-only outlines span different boundaries;
their side lengths and percentage changes are not directly interchangeable.

## Interpretation Limits

Three valid edges produce a partial reciprocal-width score, displayed in
parentheses with an amber border. Coverage is 75%, not statistical confidence.
Complete scores and partial estimates are stored separately in JSON/CSV.
Only complete scores contribute to the reference mean and summary statistics.
With fewer than three valid edges the combined score remains invalid.

A single image cannot distinguish front focus from back focus, determine height
differences in mm, or isolate a lens, sensor or holder defect. The report does not
contain calibrated MTF measurements. Print roughness, dust, black/white clipping
and image processing affect the results. Quality flags highlight these issues to
help assess whether a measurement is usable.

Measurement IDs follow image rows and columns, with X pointing right and Y down.
Automatic orientation detection, 90/180-degree rotations, physical calibration in
mm, joint analysis of focus sequences and gphoto control are not implemented yet.
Keep orientation, resolution, scale and processing consistent when comparing
reports.

The detector does not support Vlad's fine checkerboard target. An incomplete grid,
excessive rotation or ambiguous square assignment causes analysis to fail.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_target_analyzer -v
```

Tests cover a projectively distorted grid, synthetic Gaussian edge widths,
rejection of unsuitable inputs, report generation and RAW decoding parameters.
Real RAW files still require separate validation when only JPEG samples are
available.
