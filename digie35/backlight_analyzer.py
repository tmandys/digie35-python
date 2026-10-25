"""Measure spatial uniformity of a flat-field Bayer RAW image.

Uses native CFA samples, not a processed preview. Results include the lens,
sensor, diffuser and holder, and do not isolate the light panel itself.
"""
import argparse
import csv
import html
import json
from pathlib import Path

import numpy as np
import rawpy


def summarize(grid):
    grid = np.asarray(grid, dtype=float)
    if grid.ndim != 2 or not np.isfinite(grid).all() or grid.min() <= 0:
        raise ValueError("Statistics require a finite, positive 2D signal grid")
    mean = float(grid.mean())
    p5, p95 = np.percentile(grid, [5, 95])
    return {"mean": mean, "minimum": float(grid.min()), "maximum": float(grid.max()),
            "cv_percent": float(100 * grid.std() / mean),
            "p5_p95_uniformity_percent": float(100 * p5 / p95),
            "p95_p5_span_percent": float(100 * (p95-p5) / mean),
            "min_deviation_percent": float(100 * (grid.min()/mean-1)),
            "max_deviation_percent": float(100 * (grid.max()/mean-1))}


def measure_mosaic(mosaic, pattern, black, white, color_desc=b"RGBG",
                   roi=(0., 0., 1., 1.), columns=48, rows=32):
    """Bin native CFA samples into median grids with explicit source ROI.

    Clipping and low-signal fractions use all samples, not the median grid.
    The two green CFA planes are pooled within each spatial cell.
    """
    if not (4 <= rows <= 128 and 4 <= columns <= 128):
        raise ValueError("Grid dimensions must be between 4 and 128")
    pattern = np.asarray(pattern)
    desc = color_desc.decode("ascii") if isinstance(color_desc, bytes) else color_desc
    if pattern.shape != (2, 2) or sorted(desc[int(i)] for i in pattern.ravel()) != list("BGGR"):
        raise ValueError("Only a 2x2 RGB Bayer CFA is currently supported")
    x0, y0, x1, y1 = roi
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("ROI must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1")
    height, width = mosaic.shape
    # Align bounds to complete Bayer cells, preserving CFA phase.
    left, top = int(np.ceil(x0*width/2))*2, int(np.ceil(y0*height/2))*2
    right, bottom = int(x1*width/2)*2, int(y1*height/2)*2
    half_w, half_h = (right-left)//2, (bottom-top)//2
    if half_w < columns*4 or half_h < rows*4:
        raise ValueError("ROI too small for the requested grid (need at least 4x4 Bayer cells per tile)")
    xs = np.linspace(0, half_w, columns+1, dtype=int)
    ys = np.linspace(0, half_h, rows+1, dtype=int)
    channels = {}
    for color in "RGB":
        planes, clips, lows = [], 0, 0
        for py, px in np.ndindex(2, 2):
            index = int(pattern[py, px])
            if desc[index] != color:
                continue
            low, high = float(black[index]), float(white[index])
            if not np.isfinite([low, high]).all() or high <= low:
                raise ValueError("Invalid RAW black/white levels")
            data = mosaic[top+py:bottom:2, left+px:right:2].astype(np.float32)
            clips += int(np.count_nonzero(data >= high))
            lows += int(np.count_nonzero(data <= low + .01*(high-low)))
            planes.append((data-low)/(high-low))
        grid = np.empty((rows, columns), float)
        for r in range(rows):
            for c in range(columns):
                samples = np.concatenate([p[ys[r]:ys[r+1], xs[c]:xs[c+1]].ravel() for p in planes])
                grid[r, c] = np.median(samples)
        sample_count = sum(p.size for p in planes)
        flags = []
        if clips:
            flags.append("clipped_samples")
        if lows/sample_count > .01:
            flags.append("low_signal_samples")
        valid = bool(np.isfinite(grid).all() and grid.min() > .01)
        if not valid:
            flags.append("insufficient_signal_for_uniformity")
        center = float(np.median(grid[rows//2-1:rows//2+1, columns//2-1:columns//2+1]))
        stats = summarize(grid) if valid else None
        if valid:
            rh, cw = max(1, rows//10), max(1, columns//10)
            stats["corners_relative_to_center_percent"] = {
                "top_left": float(100*np.median(grid[:rh, :cw])/center),
                "top_right": float(100*np.median(grid[:rh, -cw:])/center),
                "bottom_left": float(100*np.median(grid[-rh:, :cw])/center),
                "bottom_right": float(100*np.median(grid[-rh:, -cw:])/center)}
        channels[color] = {"grid": grid.tolist(), "statistics": stats, "flags": flags,
                           "clipped_percent": 100*clips/sample_count,
                           "low_signal_percent": 100*lows/sample_count}
    combined_grid = np.mean([channels[c]["grid"] for c in "RGB"], axis=0)
    combined = {
        "grid": combined_grid.tolist(),
        "statistics": summarize(combined_grid) if all(channels[c]["statistics"] is not None for c in "RGB") else None,
        "source_flags": sorted({flag for c in "RGB" for flag in channels[c]["flags"]}),
        "definition": "Arithmetic mean of the black-subtracted, white-level-normalized R/G/B tile medians; no per-channel spatial normalization or white balance"
    }
    ratios = {}
    for numerator in "RB":
        # Ratios are not trustworthy if either channel is clipped or too weak.
        if all(channels[c]["statistics"] is not None and not channels[c]["flags"]
               for c in (numerator, "G")):
            ratio = np.array(channels[numerator]["grid"])/np.array(channels["G"]["grid"])
            ratios[numerator+"/G"] = {"grid": ratio.tolist(), "statistics": summarize(ratio)}
    return {"source_size_px": [width, height], "roi_pixels": [left, top, right, bottom],
            "roi_normalized_requested": list(roi), "grid_size": [columns, rows],
            "channels": channels, "combined": combined, "ratios": ratios}


def analyze(path, **options):
    path = Path(path)
    with rawpy.imread(str(path)) as raw:
        if raw.raw_pattern is None:
            raise ValueError("This RAW does not expose a Bayer CFA pattern")
        white = raw.camera_white_level_per_channel
        if white is None or any(v is None or v <= 0 for v in white):
            white = [raw.white_level]*4
        result = measure_mosaic(raw.raw_image_visible, raw.raw_pattern,
                                raw.black_level_per_channel, white, raw.color_desc, **options)
        result["raw_levels"] = {"black": list(raw.black_level_per_channel), "white": list(white)}
    result.update(schema_version=2, source=str(path.resolve()),
                  processing="Native Bayer CFA, black-level subtraction, per-channel white-level normalization, tile medians; no demosaic, WB, lens correction or tone curve")
    result["warnings"] = [
        "This measures the entire optical setup, including lens shading and sensor response, not the panel alone.",
        "Statistics describe tile medians, not individual pixels. Small defects may be suppressed; sample clipping is checked separately.",
        "The ROI is explicit; no automatic field cropping or lens-shading correction is applied.",
        "RGB labels denote sensor channels. Camera RGB ratios are not calibrated color temperature or photometric luminance.",
        "Do not compare mean signal as light output across exposures, LED colors or cameras without calibration.",
        "Image orientation follows the RAW raster; EXIF rotation is not applied."]
    return result


def heatmap(grid, limit):
    grid = np.asarray(grid)
    deviation = 100*(grid/grid.mean()-1)
    rows, columns = grid.shape
    rects = []
    for r, c in np.ndindex(grid.shape):
        value = float(deviation[r,c])
        t = min(1., abs(value)/limit)
        color = f"rgb(255,{int(255*(1-t))},{int(255*(1-t))})" if value >= 0 else f"rgb({int(255*(1-t))},{int(255*(1-t))},255)"
        rects.append(f'<rect x="{c*10}" y="{r*10}" width="10" height="10" fill="{color}"><title>Column {c+1}, row {r+1}: {value:+.2f}%</title></rect>')
    return f'<svg role="img" aria-label="Relative signal deviation map" viewBox="0 0 {columns*10} {rows*10}">{"".join(rects)}</svg>'


def profile_svg(grid, limit):
    grid = np.asarray(grid)
    rows, columns = grid.shape
    profiles = [np.median(grid[rows//2-1:rows//2+1, :],axis=0),
                np.median(grid[:, columns//2-1:columns//2+1],axis=1)]
    lines = ['<line x1="20" y1="85" x2="580" y2="85" stroke="#999"/>']
    for values, color in zip(profiles, ["#007c91", "#b34400"]):
        values = 100*(values/grid.mean()-1)
        points = " ".join(f'{20+i*560/(len(values)-1):.2f},{85-65*np.clip(v/limit,-1,1):.2f}' for i,v in enumerate(values))
        lines.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
    return '<svg viewBox="0 0 600 180" role="img" aria-label="Center strip profiles">'+''.join(lines)+f'<text x="20" y="14">+{limit:g}%</text><text x="20" y="172">−{limit:g}%</text></svg>'


def write_report(result, output, map_limit=20.):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result["display_scale_percent"] = map_limit
    (output/"report.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    with (output/"grid.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["channel", "row", "column", "median_signal_fraction", "deviation_from_mean_percent"])
        for channel, data in [("Combined RGB signal", result["combined"])] + list(result["channels"].items()):
            grid = np.asarray(data["grid"])
            for r,c in np.ndindex(grid.shape):
                writer.writerow([channel, r+1, c+1, grid[r,c],
                                 100*(grid[r,c]/grid.mean()-1) if data["statistics"] else ""])
    sections = []
    for name, data in [("Combined RGB signal", result["combined"])] + list(result["channels"].items()) + list(result["ratios"].items()):
        stats = data["statistics"]
        quality = ""
        if "source_flags" in data:
            quality = ('<p>Overall camera-signal uniformity: (R + G + B) / 3, computed before spatial normalization. '
                       'Useful for white LEDs and RGB mixtures; not calibrated photometric luminance. '
                       'Channel maps remain necessary to reveal color variation.</p>'
                       f'<p>Source channel flags: {html.escape(", ".join(data["source_flags"]) or "none")}.</p>')
        if "flags" in data:
            quality = f'<p>Clipped samples: {data["clipped_percent"]:.4f}%. Samples at or below 1% of usable range: {data["low_signal_percent"]:.2f}%. Flags: {html.escape(", ".join(data["flags"]) or "none")}.</p>'
        if not stats:
            sections.append(f'<section><h2>{name}</h2>{quality}<p>Signal too weak for reliable relative uniformity.</p></section>')
            continue
        corners = stats.get("corners_relative_to_center_percent")
        corners_text = '<p>Corner / center: '+', '.join(f'{k.replace("_", " ")}: {v:.1f}%' for k,v in corners.items())+'</p>' if corners else ''
        sections.append(f'''<section><h2>{name}</h2>{quality}
<p><b>CV: {stats['cv_percent']:.2f}%</b> · <b>P5/P95: {stats['p5_p95_uniformity_percent']:.2f}%</b> · P95−P5 / mean: {stats['p95_p5_span_percent']:.2f}%</p>
<p>Tile extremes relative to mean: {stats['min_deviation_percent']:+.2f}% to {stats['max_deviation_percent']:+.2f}%.</p>{corners_text}
{heatmap(data['grid'],map_limit)}{profile_svg(data['grid'],map_limit)}</section>''')
    warnings = ''.join(f'<li>{html.escape(w)}</li>' for w in result['warnings'])
    text = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Backlight Uniformity Report</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:30px auto;padding:20px;color:#222}}section{{border-top:1px solid #ccc;margin-top:25px}}svg{{width:100%;max-width:760px;display:block}}@media print{{section{{break-inside:avoid}}}}</style>
<h1>Backlight Uniformity</h1><p>{html.escape(result['source'])}</p><p>{html.escape(result['processing'])}</p>
<p>RAW size: {result['source_size_px']}; ROI [left, top, right, bottom): {result['roi_pixels']}; grid [columns, rows]: {result['grid_size']}.</p>
<p>Maps: blue = below mean, white = mean, red = above mean. Fixed scale: ±{map_limit:g}%; values outside it use the endpoint color.
Profiles: teal = horizontal center strip; orange = vertical center strip. Profile display uses the same scale and clips outside it.</p>
<p>CV = standard deviation / mean (lower is more uniform). P5/P95 approaches 100% for a uniform field.
These are descriptive metrics, not pass/fail limits. Corner patches cover approximately 10% of each ROI dimension; center reference uses the central 2×2 tiles.</p>
<ul>{warnings}</ul>{''.join(sections)}
<p>R/G and B/G maps are omitted when either channel is clipped or has low-signal flags. Ratios use native camera channels, not sRGB.</p></html>'''
    (output/"report.html").write_text(text, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="Original Bayer RAW file, e.g. CR3 or ARW")
    parser.add_argument("--output", required=True, type=Path, help="New report directory")
    parser.add_argument("--roi", nargs=4, type=float, default=(0.,0.,1.,1.), metavar=("LEFT","TOP","RIGHT","BOTTOM"), help="Normalized ROI coordinates, default full field")
    parser.add_argument("--columns", type=int, default=48)
    parser.add_argument("--rows", type=int, default=32)
    parser.add_argument("--map-limit", type=float, default=20., help="Symmetric display range in percent")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Output directory already exists")
    if not np.isfinite(args.map_limit) or args.map_limit <= 0:
        parser.error("Map limit must be finite and positive")
    try:
        result = analyze(args.image, roi=args.roi, columns=args.columns, rows=args.rows)
        write_report(result,args.output,args.map_limit)
    except (ValueError, OSError, RuntimeError, rawpy.LibRawError) as exc:
        parser.exit(1,f"Backlight analysis failed: {exc}\n")
    for color, data in result["channels"].items():
        stats = data["statistics"]
        print(f"{color}: CV={stats['cv_percent']:.2f}%, P5/P95={stats['p5_p95_uniformity_percent']:.2f}%, flags={data['flags']}" if stats else f"{color}: insufficient signal")
    print(f"Report: {(args.output/'report.html').resolve()}")


if __name__ == "__main__":
    main()
