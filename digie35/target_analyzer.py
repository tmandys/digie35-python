"""Offline square-grid target analysis, independent of the Raspberry Pi server.

Coordinates are source-image pixels, not physical film coordinates. Edge width
is a diagnostic, not an ISO-certified SFR/MTF measurement. See docs/target-analysis.md.
"""
import argparse
import csv
import html
import json
import hashlib
import os
import shlex
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ExifTags


def load_image(path):
    """Return float32 green channel, display RGB, and processing metadata."""
    path = Path(path)
    metadata = {"file": str(path.resolve())}
    if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}:
        with Image.open(path) as image:
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Multi-page images are not supported")
            exif = image.getexif()
            values = dict(exif)
            values.update(exif.get_ifd(34665))
            metadata["exif"] = {ExifTags.TAGS.get(k, str(k)): str(v)
                                for k, v in values.items()
                                if k in {272, 33434, 33437, 34855, 37386, 42036, 274}}
            # Keep physical raster coordinates; no implicit EXIF rotation.
            if image.mode not in {"RGB", "L"}:
                raise ValueError("Use an 8-bit RGB/gray image or the original RAW")
            rgb = np.asarray(image.convert("RGB"))
        metadata["processing"] = "8-bit rendered image, green channel, no gamma inversion"
        metadata["linear"] = False
        return rgb[:, :, 1].astype(np.float32) / 255, rgb, metadata
    try:
        import rawpy
    except ImportError as exc:
        raise ValueError("RAW support requires rawpy; install requirements-target-analysis.txt") from exc
    with rawpy.imread(str(path)) as raw:
        rgb16 = raw.postprocess(output_bps=16, gamma=(1, 1), no_auto_bright=True,
                                use_camera_wb=False, use_auto_wb=False,
                                user_wb=[1, 1, 1, 1], user_flip=0,
                                output_color=rawpy.ColorSpace.raw,
                                demosaic_algorithm=rawpy.DemosaicAlgorithm.LINEAR)
    green = rgb16[:, :, 1].astype(np.float32) / 65535
    # Only the report thumbnail is display-gamma encoded.
    rgb = (np.power(np.clip(rgb16.astype(np.float32) / 65535, 0, 1), 1 / 2.2) * 255).astype(np.uint8)
    metadata.update(linear=True, processing="LibRaw linear demosaic, camera RGB, unity WB, no auto brightness")
    return green, rgb, metadata


def detect_squares(green, columns=9, rows=7):
    """Detect the regular tilted-square grid; reject markers and the outer frame.

    Small rotations/perspective are accepted. Grid identity is image-relative;
    fiducial IDs and 90/180 degree rotations are deliberately not inferred.
    """
    height, width = green.shape
    scale = min(1., 2000 / max(height, width))
    small = cv2.resize((np.clip(green, 0, 1) * 255).astype(np.uint8),
                       None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # RETR_EXTERNAL would see only the enclosing frame; include inner contours.
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if not small.size * .00025 < area < small.size * .012:
            continue
        rect = cv2.minAreaRect(contour)
        rw, rh = rect[1]
        if min(rw, rh) <= 0 or min(rw, rh) / max(rw, rh) < .75:
            continue
        if area / (rw * rh) < .80:
            continue
        candidates.append((rect, area))
    if len(candidates) < rows * columns * .5:
        raise ValueError("No sufficiently complete square-grid target found (not a Vlad target analyzer)")
    typical = float(np.median([area for _, area in candidates]))
    candidates = [(rect, area) for rect, area in candidates if .65 * typical < area < 1.4 * typical]
    centers = np.array([rect[0] for rect, _ in candidates], np.float32)

    def cluster(values, count):
        # Deterministic 1D k-means initialized over the observed grid extent.
        means = np.linspace(values.min(), values.max(), count)
        for _ in range(30):
            labels = np.abs(values[:, None] - means).argmin(axis=1)
            if any(not np.any(labels == i) for i in range(count)):
                raise ValueError("Grid rows/columns cannot be assigned; check orientation and grid dimensions")
            updated = np.array([np.mean(values[labels == i]) for i in range(count)])
            if np.max(np.abs(updated - means)) < .001:
                break
            means = updated
        return labels

    cc, rr = cluster(centers[:, 0], columns), cluster(centers[:, 1], rows)
    found = {}
    for (rect, _), col, row in zip(candidates, cc, rr):
        key = (int(row), int(col))
        if key in found:
            raise ValueError("Ambiguous grid assignment; target is too rotated or contains extra squares")
        found[key] = {"id": f"r{row + 1}c{col + 1}", "row": int(row), "column": int(col),
                      "center_px": (np.array(rect[0]) / scale).tolist(),
                      "box_px": (cv2.boxPoints(rect) / scale).tolist()}
    points = [found[k] for k in sorted(found)]
    if len(points) < rows * columns * .5:
        raise ValueError("Too few regular measurement squares")
    model = np.array([[p["column"], p["row"]] for p in points], np.float64)
    observed = np.array([p["center_px"] for p in points])
    homography, _ = cv2.findHomography(model, observed, 0)
    if homography is None:
        raise ValueError("Cannot fit target geometry")
    predicted = cv2.perspectiveTransform(model.reshape(-1, 1, 2), homography).reshape(-1, 2)
    residual = np.linalg.norm(predicted - observed, axis=1)
    pitch = np.median([rect[1][0] / scale for rect, _ in candidates])
    if np.max(residual) > pitch * .35:
        raise ValueError("Grid fit is inconsistent; do not interpret this image as the configured target")
    center = cv2.perspectiveTransform(np.array([[[(columns - 1) / 2, (rows - 1) / 2]]], np.float64), homography)[0, 0]
    geometry = {"center_px": center.tolist(),
                "offset_from_image_center_px": (center - [(width - 1) / 2, (height - 1) / 2]).tolist(),
                "grid_fit_rms_px": float(np.sqrt(np.mean(residual ** 2))),
                "grid_fit_max_px": float(np.max(residual)),
                "homography_grid_to_image": homography.tolist(),
                "orientation": "image-relative; fiducial IDs not decoded"}
    return points, geometry


def measure_edge(green, first, second, center):
    """Measure ESF 10-90 width across the middle 60% of an edge.

    Fit edge position per scan line before forming a 4x binned ESF. Preserve
    residual roughness in the ESF: it is part of the observed target+camera.
    """
    first, second, center = map(lambda p: np.asarray(p, float), (first, second, center))
    tangent = second - first
    length = np.linalg.norm(tangent)
    tangent /= length
    normal = np.array([-tangent[1], tangent[0]])
    midpoint = (first + second) / 2
    if np.dot(center - midpoint, normal) < 0:
        normal *= -1  # light outside -> dark inside
    radius = min(24, length * .16)
    along = np.arange(-length * .30, length * .30, 1.)
    across = np.arange(-radius, radius + .25, .25)
    coords = midpoint + along[:, None, None] * tangent + across[None, :, None] * normal
    h, w = green.shape
    if (coords[..., 0].min() < 0 or coords[..., 0].max() >= w - 1 or
            coords[..., 1].min() < 0 or coords[..., 1].max() >= h - 1):
        return {"valid": False, "reason": "edge crop outside image"}
    sampled = cv2.remap(green, coords[..., 0].astype(np.float32), coords[..., 1].astype(np.float32), cv2.INTER_LINEAR)
    light = float(np.median(sampled[:, :max(2, len(across)//8)]))
    dark = float(np.median(sampled[:, -max(2, len(across)//8):]))
    contrast = light - dark
    if contrast < .03 or len(along) < 24:
        return {"valid": False, "reason": "insufficient contrast or edge length"}
    positions = across[np.argmin(np.abs(sampled - (light + dark) / 2), axis=1)]
    fit = np.polyfit(along, positions, 1)
    residual = positions - np.polyval(fit, along)
    # Profile in the fitted normal direction, retaining print/edge irregularity.
    distances = (across[None, :] - np.polyval(fit, along)[:, None]) / np.sqrt(1 + fit[0] ** 2)
    bins = np.rint((distances.ravel() + radius) * 4).astype(int)
    good = (bins >= 0) & (bins <= int(radius * 8))
    counts = np.bincount(bins[good], minlength=int(radius * 8) + 1)
    sums = np.bincount(bins[good], weights=sampled.ravel()[good], minlength=len(counts))
    valid = counts > 0
    x = (np.arange(len(counts))[valid] / 4) - radius
    profile = (sums[valid] / counts[valid] - dark) / contrast
    # Monotonic envelope reduces noise crossings; this is a diagnostic width,
    # not a standards-compliant SFR calculation.
    profile = np.minimum.accumulate(np.clip(profile, 0, 1))
    def crossing(level):
        indices = np.where(profile <= level)[0]
        if not len(indices) or indices[0] == 0:
            return None
        i = indices[0]
        return float(np.interp(level, [profile[i], profile[i-1]], [x[i], x[i-1]]))
    a, b = crossing(.9), crossing(.1)
    if a is None or b is None or b <= a:
        return {"valid": False, "reason": "edge transition not contained in crop"}
    flags = []
    if dark <= 1 / 255:
        flags.append("black_floor")
    if light >= 254 / 255:
        flags.append("white_ceiling")
    roughness = float(np.std(residual))
    if roughness > 1:
        flags.append("rough_or_irregular_edge")
    return {"valid": True, "width_10_90_px": b - a,
            "sharpness_inv_px": 1 / (b - a), "roughness_rms_px": roughness,
            "dark_level": dark, "light_level": light,
            "direction": "X" if abs(normal[0]) > abs(normal[1]) else "Y", "flags": flags}


def load_reference(path, frame=1, columns=9, rows=7):
    """Extract a framed target from a horizontal source strip, left to right.

    Source pixels define geometry only. TIFF DPI is nominal print metadata,
    never a measurement of the manufactured target.
    """
    path = Path(path)
    with Image.open(path) as source:
        gray = np.asarray(source.convert("L"))
        dpi = source.info.get("dpi")
        dpi = [float(v) for v in dpi] if dpi else None
    height, width = gray.shape
    _, mask = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h < height*.45 or w < height*.45 or w*h > width*height*.95:
            continue
        if not .5 < w/h < 2.5:
            continue
        boxes.append((x, y, w, h))
    # Keep the outer boundary of each frame, not its duplicate inner contour.
    frames = []
    for box in sorted(boxes, key=lambda b: b[2]*b[3], reverse=True):
        x,y,w,h = box
        if not any(a <= x and b <= y and x+w <= a+c and y+h <= b+d
                   for a,b,c,d in frames):
            frames.append(box)
    frames.sort(key=lambda b: b[0])
    if not frames or not 1 <= frame <= len(frames):
        raise ValueError(f"Reference frame must be between 1 and {len(frames)}; detected {len(frames)} framed targets")
    x,y,w,h = frames[frame-1]
    points, _ = detect_squares(gray[y:y+h,x:x+w].astype(np.float32)/255, columns, rows)
    for p in points:
        p["center_normalized"] = [p["center_px"][0]/w, p["center_px"][1]/h]
    return {"file": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "strip_size_px": [width,height], "frame_count": len(frames), "selected_frame": frame,
            "frame_box_px": [x,y,w,h], "dpi": list(dpi) if dpi else None,
            "nominal_frame_mm": [25.4*w/dpi[0],25.4*h/dpi[1]] if dpi and min(dpi)>0 else None,
            "points": points,
            "note": "Frame bounds include the printed border. DPI-derived dimensions are nominal only; no physical calibration is applied."}


def apply_reference(points, reference):
    source = {p["id"]: p for p in reference["points"]}
    matches = [p for p in points if p["id"] in source]
    if len(matches) < max(4, len(source)*.8) or any(p["id"] not in source for p in points):
        raise ValueError("Detected grid does not match the reference layout")
    model = np.array([source[p["id"]]["center_normalized"] for p in matches], np.float64)
    observed = np.array([p["center_px"] for p in matches], np.float64)
    transform, _ = cv2.findHomography(model, observed, 0)
    if transform is None:
        raise ValueError("Cannot fit reference geometry")
    projected = cv2.perspectiveTransform(model[:,None,:],transform)[:,0,:]
    residual = np.linalg.norm(projected-observed,axis=1)
    for p, error in zip(matches,residual):
        p["reference_center_normalized"] = source[p["id"]]["center_normalized"]
        p["reference_residual_px"] = float(error)
    frame = cv2.perspectiveTransform(np.array([[[0.,0.],[1.,0.],[1.,1.],[0.,1.],[.5,.5]]]),transform)[0]
    return {"reference_fit_rms_px": float(np.sqrt(np.mean(residual**2))),
            "reference_fit_max_px": float(residual.max()),
            "reference_frame_corners_px": frame[:4].tolist(),
            "reference_frame_center_px": frame[4].tolist(),
            "homography_reference_to_image": transform.tolist()}


def quadrilateral_metrics(corners):
    """Image coordinates: TL, TR, BR, BL; positive angles are clockwise."""
    c = np.asarray(corners, dtype=float)
    vectors = [c[1]-c[0], c[2]-c[3], c[3]-c[0], c[2]-c[1]]
    lengths = dict(zip(("top", "bottom", "left", "right"),
                       map(float, np.linalg.norm(vectors, axis=1))))
    angles = {name: float(np.degrees(np.arctan2(v[1], v[0])) - (90 if i > 1 else 0))
              for i, (name, v) in enumerate(zip(lengths, vectors))}
    return {"side_lengths_px": lengths, "side_angles_deg": angles,
            "rotation_horizontal_mean_deg": (angles["top"] + angles["bottom"])/2,
            "bottom_minus_top_px": lengths["bottom"]-lengths["top"],
            "right_minus_left_px": lengths["right"]-lengths["left"],
            "width_change_percent": 200*(lengths["bottom"]-lengths["top"])/(lengths["bottom"]+lengths["top"]),
            "height_change_percent": 200*(lengths["right"]-lengths["left"])/(lengths["right"]+lengths["left"])}


def analyze_geometry(points, columns=9, rows=7, use_reference=False):
    """Fit geometry and leave-line-out sensitivity, not statistical confidence.

    The reference frame is extrapolated from centers, not border detection.
    """
    model = np.array([p["reference_center_normalized"] if use_reference else
                      [p["column"]/(columns-1), p["row"]/(rows-1)] for p in points], float)
    observed = np.array([p["center_px"] for p in points], float)
    boundary = np.array([[[0., 0.], [1., 0.], [1., 1.], [0., 1.]]])

    def fit(mask):
        src, dst = model[mask], observed[mask]
        if len(src) < 4 or np.linalg.matrix_rank(np.column_stack((src, np.ones(len(src))))) < 3:
            return None
        h, _ = cv2.findHomography(src, dst, 0)
        if h is None or not np.all(np.isfinite(h)):
            return None
        denominators = np.column_stack((boundary[0], np.ones(4))) @ h[2]
        if np.min(np.abs(denominators)) < 1e-9 or np.min(denominators)*np.max(denominators) <= 0:
            return None
        return h, cv2.perspectiveTransform(boundary, h)[0]

    fitted = fit(np.ones(len(points), dtype=bool))
    if fitted is None:
        raise ValueError("Cannot estimate a finite target quadrilateral")
    h, corners = fitted
    result = quadrilateral_metrics(corners)
    projected = cv2.perspectiveTransform(model[:, None, :], h)[:, 0, :]
    a = np.column_stack((model, np.ones(len(model))))
    affine = a @ np.linalg.lstsq(a, observed, rcond=None)[0]
    result.update(corners_px=corners.tolist(),
                  boundary="source frame (inferred)" if use_reference else "outer grid centers (not target border)",
                  projective_rms_px=float(np.sqrt(np.mean(np.sum((projected-observed)**2, axis=1)))),
                  affine_rms_px=float(np.sqrt(np.mean(np.sum((affine-observed)**2, axis=1)))))
    trials = []
    keys = ("width_change_percent", "height_change_percent", "rotation_horizontal_mean_deg")
    for axis in ("row", "column"):
        for value in sorted({p[axis] for p in points}):
            fitted = fit(np.array([p[axis] != value for p in points]))
            if fitted is not None:
                metrics = quadrilateral_metrics(fitted[1])
                trials.append({"omitted_axis": axis, "omitted_index": value,
                               **{key: metrics[key] for key in keys}})
    result["leave_line_out"] = trials
    result["sensitivity_ranges"] = {
        key: [min(t[key] for t in trials), max(t[key] for t in trials)] if trials else None
        for key in keys}
    result["note"] = ("Positive rotation is clockwise. Width change = (bottom-top)/mean; height change = (right-left)/mean. "
                      "Rotation is the mean of the two horizontal side angles. Vertical angles are relative to vertical. "
                      "Leave-line-out ranges are sensitivity checks, not confidence intervals. "
                      "Perspective, lens distortion, target errors and detection errors are not separated; no physical tilt angle is inferred.")
    return result


def measure_focus_score(rgb, center, size=96):
    """Online-equivalent Laplacian variance on a centered 8-bit RGB ROI.

    RAW callers use the display RGB returned by load_image, not linear green.
    This matches the formula and sample range, not the camera JPEG processing.
    """
    height, width = rgb.shape[:2]
    x = min(width-1, max(0, int(center[0])))
    y = min(height-1, max(0, int(center[1])))
    rw, rh = min(size, width), min(size, height)
    left = min(max(0, x-rw//2), width-rw)
    top = min(max(0, y-rh//2), height-rh)
    roi = rgb[top:top+rh, left:left+rw]
    scores = {name: float(cv2.Laplacian(channel, cv2.CV_64F).var())
              for name, channel in zip(("red", "green", "blue"), cv2.split(roi))}
    return {"focus_score": max(scores.values()), "focus_scores": scores,
            "focus_channel": max(scores, key=scores.get), "bounds": [left, top, rw, rh]}


def add_focus_scores(report, rgb):
    for point in report["points"]:
        point["focus"] = measure_focus_score(rgb, point["center_px"])
    report["focus_measurement"] = {
        "roi_size_px": 96, "position": "detected square center",
        "formula": "max(var(Laplacian(R)), var(Laplacian(G)), var(Laplacian(B)))",
        "processing": ("8-bit display RGB: linear camera RGB encoded with power 1/2.2, unity WB, no auto brightness"
                       if report["source"]["linear"] else "Original decoded 8-bit RGB"),
        "note": "Same formula as online focus, but RAW rendering differs from camera JPEG. Centered ROIs may contain only a flat square interior and measure texture/noise rather than edge sharpness. No contrast normalization or noise subtraction."}


def add_partial_measurements(points):
    """Keep complete scores separate from three-edge estimates."""
    for point in points:
        widths = [e["width_10_90_px"] for e in point["edges"] if e["valid"]]
        point["valid_edge_count"] = len(widths)
        point["edge_coverage_percent"] = 25 * len(widths)
        point["measurement_status"] = "Complete" if len(widths) == 4 else "Partial" if len(widths) == 3 else "Invalid"
        point["partial_sharpness_inv_px"] = float(1 / np.mean(widths)) if len(widths) == 3 else None


def analyze(path, columns=9, rows=7, reference_path=None, reference_frame=1):
    green, rgb, metadata = load_image(path)
    points, geometry = detect_squares(green, columns, rows)
    reference = None
    if reference_path is not None:
        reference = load_reference(reference_path, reference_frame, columns, rows)
        geometry.update(apply_reference(points, reference))
    geometry["quadrilateral"] = analyze_geometry(points, columns, rows, reference is not None)
    for point in points:
        box = point["box_px"]
        edges = [measure_edge(green, box[i], box[(i + 1) % 4], point["center_px"]) for i in range(4)]
        point["edges"] = edges
        for direction in ("X", "Y"):
            widths = [e["width_10_90_px"] for e in edges if e["valid"] and e["direction"] == direction]
            point[f"width_{direction}_px"] = float(np.median(widths)) if widths else None
        widths = [e["width_10_90_px"] for e in edges if e["valid"]]
        point["sharpness_inv_px"] = float(1 / np.mean(widths)) if len(widths) == 4 else None
    add_partial_measurements(points)
    scores = [p["sharpness_inv_px"] for p in points if p["sharpness_inv_px"] is not None]
    if not scores:
        raise ValueError("No valid edge measurements")
    warnings = ["A single image cannot determine the direction of defocus, height differences in mm, or a faulty component.",
                "Measurements include the target, optics, sensor and processing; this is not calibrated MTF.",
                "Orientation is image-relative, not based on marker IDs. Rotating the image changes measurement IDs.",
                "Geometric deviations include target manufacturing errors, lens distortion and perspective."]
    if not metadata["linear"]:
        warnings.append("JPEG/rendered image: the nonlinear tone curve and sharpening affect edge widths.")
    if reference is not None:
        warnings.append("Reference registration assumes the same orientation as the source frame; marker IDs are not decoded. Source DPI is not physical calibration.")
        warnings.append("The raster reference constrains geometry only. Its edge rasterization is not removed from sharpness measurements.")
    flag_counts = {}
    for point in points:
        for edge in point["edges"]:
            for flag in edge.get("flags", []):
                flag_counts[flag] = flag_counts.get(flag, 0) + 1
    summary = {"detected_squares": len(points), "valid_squares": len(scores),
               "mean_sharpness_inv_px": float(np.mean(scores)),
               "relative_range_percent": float(100 * (max(scores) - min(scores)) / np.mean(scores)),
               "edge_quality_flags": flag_counts}
    usable = [p for p in points if p["sharpness_inv_px"] is not None]
    summary["weakest_point"] = min(usable, key=lambda p: p["sharpness_inv_px"])["id"]
    summary["strongest_point"] = max(usable, key=lambda p: p["sharpness_inv_px"])["id"]
    corners = [p for p in usable if p["row"] in (0, rows-1) and p["column"] in (0, columns-1)]
    if len(corners) == 4:
        values = [p["sharpness_inv_px"] for p in corners]
        summary["corner_relative_range_percent"] = float(100 * (max(values)-min(values)) / np.mean(values))
    if flag_counts.get("black_floor"):
        warnings.append("Some edges have dark levels near zero. Check the RAW and exposure; edge profiles may be clipped.")
    if flag_counts.get("rough_or_irregular_edge"):
        warnings.append("Irregular edges detected. Printing, dust or target texture may significantly limit the results.")
    report = {"schema_version": 2, "source": metadata, "image_size": [green.shape[1], green.shape[0]],
              "grid": {"columns": columns, "rows": rows}, "geometry": geometry,
              "summary": summary, "warnings": warnings, "points": points}
    if reference is not None:
        report["reference"] = reference
    add_focus_scores(report, rgb)
    return report, rgb


def draw_geometry_overlay(preview, geometry, image_size):
    """Add an unexaggerated fitted outline, dimension lines and angle labels."""
    margin_x, margin_y = 180, 120
    canvas = Image.new("RGB", (preview.width+2*margin_x, preview.height+2*margin_y), "#101923")
    canvas.paste(preview, (margin_x, margin_y))
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    small = ImageFont.load_default(size=15)
    scale = np.array([preview.width/image_size[0], preview.height/image_size[1]])
    corners = np.array(geometry["corners_px"])*scale + [margin_x, margin_y]
    cyan = "#4de8ff"

    def label(position, text, color="white", size=font):
        x, y = position
        bounds = draw.textbbox((0, 0), text, font=size)
        w, h = bounds[2]-bounds[0], bounds[3]-bounds[1]
        x = min(max(x-w/2, 5), canvas.width-w-5)
        y = min(max(y-h/2, 5), canvas.height-h-8)
        draw.rectangle((x-4, y-3, x+w+4, y+h+8), fill="#101923")
        draw.text((x, y), text, font=size, fill=color)

    draw.line([tuple(p) for p in corners]+[tuple(corners[0])], fill=cyan, width=3)
    for i, p in enumerate(corners):
        draw.ellipse((p[0]-5, p[1]-5, p[0]+5, p[1]+5), fill=cyan)
        label(p+[0, 17 if i < 2 else -20], ("TL", "TR", "BR", "BL")[i], cyan, small)
    center = corners.mean(axis=0)
    for name, i, j in (("top", 0, 1), ("bottom", 3, 2), ("left", 0, 3), ("right", 1, 2)):
        p, q = corners[i], corners[j]
        tangent = (q-p)/np.linalg.norm(q-p)
        normal = np.array([-tangent[1], tangent[0]])
        if np.dot(normal, (p+q)/2-center) < 0:
            normal *= -1
        a, b = p+normal*32, q+normal*32
        draw.line([tuple(a), tuple(b)], fill=cyan, width=1)
        for base, end in ((p, a), (q, b)):
            draw.line([tuple(base), tuple(end+normal*7)], fill=cyan, width=1)
            draw.line([tuple(end-normal*5-tangent*4), tuple(end+normal*5+tangent*4)], fill=cyan, width=2)
        position = (a+b)/2
        if name in ("left", "right"):
            position += normal*65
        label(position, f"{name.title()}: {geometry['side_lengths_px'][name]:.1f} px", cyan, small)
    # Horizontal baseline at TL makes the sign of the top-side angle explicit.
    p = corners[0]
    draw.line([tuple(p), (p[0]+min(220, preview.width*.25), p[1])], fill="#ffc857", width=2)
    label((canvas.width/2, 25), "Fitted quadrilateral | " + geometry["boundary"], cyan)
    label((canvas.width/2, 55), f"Rotation: {geometry['rotation_horizontal_mean_deg']:+.3f} deg (horizontal-side mean; + clockwise)")
    label((canvas.width/2, 83), f"Top: {geometry['side_angles_deg']['top']:+.3f} deg | Bottom: {geometry['side_angles_deg']['bottom']:+.3f} deg | Yellow: horizontal", size=small)
    y = canvas.height-80
    label((canvas.width/2, y), f"Bottom - top: {geometry['bottom_minus_top_px']:+.1f} px ({geometry['width_change_percent']:+.3f}%)")
    label((canvas.width/2, y+28), f"Right - left: {geometry['right_minus_left_px']:+.1f} px ({geometry['height_change_percent']:+.3f}%)")
    label((canvas.width/2, y+56), "Lengths are source-image pixels. Outline inferred from centers; deformation is not exaggerated.", size=small)
    return canvas


def add_report_magnifier(document):
    """Self-contained local-file viewer; also upgrades existing HTML reports."""
    if 'id="map-magnifier"' in document:
        return document
    controls = '''<div class="map-controls"><label for="map-zoom">Magnifier:</label>
<select id="map-zoom"><option value="4">4× displayed size</option>
<option value="native">1:1 map pixels</option><option value="off">Off</option></select>
<span>Move over the map. 1:1 refers to the annotated map, not the original RAW.</span></div>'''
    document = document.replace('<img src="map.png"', controls + '<img id="sharpness-map" src="map.png"', 1)
    extra = '''
<style>
.map-controls {display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:12px 0}
.map-controls select {font:inherit;padding:5px}.map-controls span {font-size:13px;color:#555}
#map-magnifier {position:fixed;pointer-events:none;z-index:1000;width:320px;height:240px;
border:2px solid #4de8ff;border-radius:8px;background-color:#101923;background-repeat:no-repeat;
box-shadow:0 4px 20px #0008;box-sizing:border-box}
#map-magnifier[hidden] {display:none}
#map-magnifier::after {content:"+";position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
color:#4de8ff;text-shadow:0 0 2px black;font:18px monospace}
@media print {.map-controls,#map-magnifier {display:none!important}}
</style>
<div id="map-magnifier" hidden aria-hidden="true"></div>
<script>
(() => {
  const map = document.getElementById('sharpness-map');
  const lens = document.getElementById('map-magnifier');
  const mode = document.getElementById('map-zoom');
  if (!map || !lens || !mode) return;
  const hide = () => { lens.hidden = true; };
  map.addEventListener('pointermove', event => {
    if (mode.value === 'off' || !map.naturalWidth) { hide(); return; }
    const rect = map.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const width = Math.min(320, window.innerWidth - 16);
    const height = Math.min(240, window.innerHeight - 16);
    lens.style.width = width + 'px'; lens.style.height = height + 'px';
    const factor = mode.value === 'native' ? map.naturalWidth / rect.width : 4;
    lens.style.backgroundImage = 'url("' + map.currentSrc + '")';
    lens.style.backgroundSize = `${rect.width * factor}px ${rect.height * factor}px`;
    // Background positioning is relative to the padding box inside the border.
    lens.style.backgroundPosition = `${(width-4)/2 - (event.clientX-rect.left)*factor}px ${(height-4)/2 - (event.clientY-rect.top)*factor}px`;
    let top = event.clientY - height - 24;
    if (top < 8) top = event.clientY + 24;
    top = Math.max(8, Math.min(top, window.innerHeight-height-8));
    const left = Math.max(8, Math.min(event.clientX-width/2, window.innerWidth-width-8));
    lens.style.left = left + 'px'; lens.style.top = top + 'px'; lens.hidden = false;
  });
  map.addEventListener('pointerleave', hide);
  map.addEventListener('pointercancel', hide);
  mode.addEventListener('change', hide);
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  window.addEventListener('blur', hide);
})();
</script>
'''
    return document.replace('</html>', extra + '</html>')


def write_report(report, rgb, destination, *, overwrite=False):
    add_partial_measurements(report["points"])
    add_focus_scores(report, rgb)
    # Also support regenerating reports from previously saved measurements.
    report["geometry"]["quadrilateral"] = analyze_geometry(
        report["points"], report["grid"]["columns"], report["grid"]["rows"], "reference" in report)
    report["schema_version"] = 2
    scores = [p["sharpness_inv_px"] for p in report["points"] if p["sharpness_inv_px"] is not None]
    mean_score = float(np.mean(scores))
    complete = [p for p in report["points"] if p["sharpness_inv_px"] is not None]
    report["summary"].update(
        valid_squares=len(complete), mean_sharpness_inv_px=mean_score,
        relative_range_percent=100*(max(scores)-min(scores))/mean_score,
        weakest_point=min(complete, key=lambda p: p["sharpness_inv_px"])["id"],
        strongest_point=max(complete, key=lambda p: p["sharpness_inv_px"])["id"])
    for p in report["points"]:
        score = p["sharpness_inv_px"] if p["sharpness_inv_px"] is not None else p["partial_sharpness_inv_px"]
        p["sharpness_deviation_percent"] = 100*(score/mean_score-1) if score is not None else None
    report["map_color_scale"] = {"neutral_band_percent": 5, "saturation_percent": 20,
                                 "reference": "arithmetic mean of fully valid square scores",
                                 "note": "Display thresholds only; not measurement uncertainty or a tolerance test."}
    destination = Path(destination)
    command_args = [sys.executable, "-m", "digie35.target_analyzer", report["source"]["file"],
                    "--columns", str(report["grid"]["columns"]), "--rows", str(report["grid"]["rows"])]
    if "reference" in report:
        command_args += ["--reference", report["reference"]["file"],
                         "--reference-frame", str(report["reference"]["selected_frame"])]
    command_args += ["--output", str(destination.resolve())]
    working_directory = str(Path(__file__).resolve().parent.parent)
    if os.name == "nt":
        def quote(value):
            return "'" + value.replace("'", "''") + "'"
        command = "Set-Location -LiteralPath " + quote(working_directory) + "\n& " + " ".join(map(quote, command_args))
        shell_name = "PowerShell"
    else:
        command = "cd " + shlex.quote(working_directory) + " &&\n" + shlex.join(command_args)
        shell_name = "POSIX shell"
    report["reproduction"] = {"shell": shell_name, "working_directory": working_directory,
                              "argv": command_args, "command": command,
                              "note": "Equivalent command reconstructed from report settings, not a historical shell log. Choose a new output directory before rerunning."}
    destination.mkdir(parents=True, exist_ok=overwrite)
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    with (destination / "measurements.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(["id", "x_px", "y_px", "width_X_px", "width_Y_px", "sharpness_inv_px", "sharpness_deviation_percent", "focus_score", "focus_channel", "flags", "partial_sharpness_inv_px", "valid_edge_count", "edge_coverage_percent", "measurement_status"])
        for p in report["points"]:
            flags = sorted({f for edge in p["edges"] for f in edge.get("flags", [])})
            writer.writerow([p["id"], *p["center_px"], p["width_X_px"], p["width_Y_px"], p["sharpness_inv_px"], p["sharpness_deviation_percent"], p["focus"]["focus_score"], p["focus"]["focus_channel"], ",".join(flags), p["partial_sharpness_inv_px"], p["valid_edge_count"], p["edge_coverage_percent"], p["measurement_status"]])
    preview = Image.fromarray(rgb)
    preview.thumbnail((1600, 1600))
    scale = preview.width / rgb.shape[1]
    draw = ImageDraw.Draw(preview)
    label_font = ImageFont.load_default(size=12)
    for p in report["points"]:
        score = p["sharpness_inv_px"] if p["sharpness_inv_px"] is not None else p["partial_sharpness_inv_px"]
        deviation = p["sharpness_deviation_percent"]
        color = (180, 180, 180)
        if deviation is None:
            color = (235, 180, 55)
        elif abs(deviation) > 5:
            strength = min(1., (abs(deviation)-5)/15)
            endpoint = (55, 220, 95) if deviation > 0 else (245, 65, 55)
            color = tuple(round(180 + strength*(channel-180)) for channel in endpoint)
        if p["measurement_status"] == "Partial":
            color = (235, 180, 55)
        box = [(x * scale, y * scale) for x, y in p["box_px"]]
        draw.line(box + [box[0]], fill=color, width=3)
        x, y = np.mean(box, axis=0)
        label = p["id"] + (f"\n{score:.4f}\n{deviation:+.1f}%" if score is not None else "\ninvalid")
        if p["measurement_status"] == "Partial":
            label = f"{p['id']}\n({score:.4f})\n({deviation:+.1f}%)"
        label += f"\nF {p['focus']['focus_score']:.1f}"
        bounds = draw.multiline_textbbox((0, 0), label, font=label_font, spacing=3, align="center")
        draw.multiline_text((x-(bounds[2]+bounds[0])/2, y-(bounds[3]+bounds[1])/2),
                            label, font=label_font, spacing=3, align="center",
                            fill="white", stroke_width=1, stroke_fill="black")
    legend = Image.new("RGB", (preview.width, 70), "#101923")
    legend_draw = ImageDraw.Draw(legend)
    legend_draw.text((18, 10), "Labels: location / reciprocal width (px^-1) / deviation / F = Laplacian focus (96x96 center ROI). Gray: within +/-5%.", font=label_font, fill="white")
    legend_draw.text((18, 37), "Red: below mean. Green: above mean. Full color at +/-20%. Amber: partial/invalid. Parentheses: 3/4 edges, not confidence.", font=label_font, fill="white")
    preview = draw_geometry_overlay(preview, report["geometry"]["quadrilateral"], report["image_size"])
    combined = Image.new("RGB", (preview.width, preview.height+legend.height), "#101923")
    combined.paste(preview, (0, 0))
    combined.paste(legend, ((preview.width-legend.width)//2, preview.height))
    preview = combined
    preview.save(destination / "map.png")
    def fmt(v):
        return "—" if v is None else f"{v:.3f}"
    def display_score(p):
        if p["sharpness_inv_px"] is not None:
            return f"{p['sharpness_inv_px']:.4f}"
        if p["partial_sharpness_inv_px"] is not None:
            return f"({p['partial_sharpness_inv_px']:.4f})"
        return "—"
    table = "".join(f"<tr><td>{p['id']}</td><td>{fmt(p['width_X_px'])}</td><td>{fmt(p['width_Y_px'])}</td><td>{display_score(p)}</td><td>{format(p['sharpness_deviation_percent'], '+.1f')+'%' if p['sharpness_deviation_percent'] is not None else '—'}</td><td>{p['focus']['focus_score']:.2f}</td><td>{p['focus']['focus_channel']}</td><td>{p['measurement_status']} — {p['valid_edge_count']}/4 edges ({p['edge_coverage_percent']}%). {html.escape(', '.join(sorted({f for e in p['edges'] for f in e.get('flags', [])})))}</td></tr>" for p in report["points"])
    stats = report["summary"]
    geometry = report["geometry"]
    dx, dy = geometry["offset_from_image_center_px"]
    summary = f"""<p>Detected <b>{stats['detected_squares']}</b> squares; fully evaluated <b>{stats['valid_squares']}</b>.
Weakest location: <b>{stats['weakest_point']}</b>; strongest: <b>{stats['strongest_point']}</b>.</p>
<p>Relative range across all locations: <b>{stats['relative_range_percent']:.1f} %</b>.
Relative range across the four outer corners: <b>{fmt(stats.get('corner_relative_range_percent'))} %</b>.
Range = (maximum − minimum) / mean; percentages describe the reciprocal edge-width diagnostic, not resolution.</p>"""
    geometry_text = f"""<p>Grid center relative to image center: <b>X {dx:+.1f} px, Y {dy:+.1f} px</b> (X right, Y down).
Deviation of square centers from the fitted projective grid: RMS <b>{geometry['grid_fit_rms_px']:.2f} px</b>.
The grid center does not measure the optical axis. Millimeters and magnification require a dimensional reference.</p>"""
    quad = geometry["quadrilateral"]
    sides = "".join(f"<tr><td>{name.title()}</td><td>{quad['side_lengths_px'][name]:.2f}</td><td>{quad['side_angles_deg'][name]:+.4f}</td></tr>"
                    for name in ("top", "bottom", "left", "right"))
    sensitivity = "".join(
        f"<tr><td>{title}</td><td>{quad[key]:+.4f}</td><td>"
        + (f"{limits[0]:+.4f} to {limits[1]:+.4f}" if limits else "Unavailable") + "</td></tr>"
        for key, title in (("width_change_percent", "Bottom vs top (%)"),
                           ("height_change_percent", "Right vs left (%)"),
                           ("rotation_horizontal_mean_deg", "Rotation (deg)"))
        for limits in [quad["sensitivity_ranges"][key]])
    geometry_text += f"""<h3>Perspective and Rotation</h3>
<p>Boundary: <b>{html.escape(quad['boundary'])}</b>. Cyan outline and dimensions in the map use the original image geometry.</p>
<table><tr><th>Side</th><th>Length (source px)</th><th>Angle (deg)</th></tr>{sides}</table>
<p>Top/bottom angles are relative to horizontal; left/right angles are relative to vertical. Positive angles are clockwise.</p>
<table><tr><th>Measurement</th><th>Full fit</th><th>Leave-one-row/column-out range</th></tr>{sensitivity}</table>
<p>Affine fit RMS: <b>{quad['affine_rms_px']:.3f} px</b>; projective fit RMS: <b>{quad['projective_rms_px']:.3f} px</b>.
The affine model allows rotation, scale and shear, but no perspective convergence.
A small RMS improvement or a sensitivity range crossing zero provides weak support for perspective convergence.</p>
<p>{html.escape(quad['note'])}</p>"""
    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in report["warnings"])
    reference_text = ""
    if "reference" in report:
        ref = report["reference"]
        reference_text = f"""<h2>Source Reference</h2><p>{html.escape(ref['file'])}</p>
<p>Frame {ref['selected_frame']} of {ref['frame_count']} (left to right).
Source frame size: {ref['frame_box_px'][2]} × {ref['frame_box_px'][3]} px.
Nominal DPI: {ref['dpi']}. Nominal frame size in mm: {ref['nominal_frame_mm']}.</p>
<p>Reference-fit RMS: {geometry['reference_fit_rms_px']:.2f} px.
{html.escape(ref['note'])}</p>"""
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Digie35 — Target Analysis Report</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:35px auto;padding:20px;color:#222}}img{{width:100%}}td,th{{padding:6px 16px;text-align:right;border-bottom:1px solid #ddd}}pre{{white-space:pre-wrap}}@media print{{body{{margin:0}}tr{{break-inside:avoid}}}}</style>
<h1>Digie35 — Target Analysis</h1><p>{html.escape(report['source']['file'])}</p>
<p>{html.escape(report['source']['processing'])}</p><ul>{warnings}</ul>
<h2>Sharpness Map</h2><p>Each square shows its location, reciprocal edge width (px⁻¹), and signed percentage deviation from the arithmetic mean of fully valid squares ({mean_score:.4f} px⁻¹). This is not the Laplacian focus score.</p>
<p>Gray: within ±5% of the mean. Beyond this band, red indicates lower and green higher sharpness, reaching full color at ±20%. Amber indicates an invalid measurement. Fixed display thresholds avoid exaggerating small differences; they do not establish statistical significance or a tolerance pass.</p><img src="map.png" alt="Sharpness labels and fixed-scale deviations from the mean, with fitted target geometry">
<h2>Summary</h2>{summary}<h2>Geometry in Pixels</h2>{geometry_text}{reference_text}
<p>Parenthesized scores and deviations are partial estimates from 3/4 edges (75% coverage, not confidence). Partial and invalid measurements have amber borders. Partial scores are excluded from the reference mean and summary statistics; fewer than three valid edges remain invalid.</p>
<h2>Measurement Locations</h2><p>10–90% transition width in pixels, measured in the X/Y directions. Sharpness is the reciprocal of the mean of all four edge widths; higher means sharper. Deviation and colors refer to this edge metric, not the Laplacian focus score.</p>
<p><b>F / Focus score:</b> maximum RGB-channel variance of the Laplacian in a 96 × 96 source-pixel ROI centered on each square. Processing: {html.escape(report['focus_measurement']['processing'])}.</p>
<p>{html.escape(report['focus_measurement']['note'])} Per-channel scores and exact ROI bounds are stored in JSON.</p>
<p>black_floor = dark level near zero; white_ceiling = light level near maximum; rough_or_irregular_edge = irregular edge.
No individual flag identifies the cause of a defect. The JSON report contains per-edge details.</p>
<table><tr><th>Location</th><th>X Width</th><th>Y Width</th><th>Sharpness (1/px)</th><th>Deviation</th><th>Focus score</th><th>Focus channel</th><th>Quality Flags</th></tr>{table}</table>
<h2>Reproduce This Analysis</h2><p>Equivalent command for {shell_name}, reconstructed from the report settings. It is not a historical shell log.
Choose a new <code>--output</code> directory before running: existing reports are never overwritten.</p>
<pre><code>{html.escape(command)}</code></pre></html>"""
    (destination / "report.html").write_text(add_report_magnifier(document), encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New report directory (must not exist)")
    parser.add_argument("--columns", type=int, default=9)
    parser.add_argument("--rows", type=int, default=7)
    parser.add_argument("--reference", type=Path, help="Source artwork with one or more framed targets")
    parser.add_argument("--reference-frame", type=int, default=1, help="Source frame number, left to right (default: 1)")
    args = parser.parse_args(argv)
    if not 3 <= args.columns <= 50 or not 3 <= args.rows <= 50:
        parser.error("rows and columns must be between 3 and 50")
    if args.output.exists():
        parser.error("output directory already exists; choose a new directory")
    try:
        report, rgb = analyze(args.image, args.columns, args.rows, args.reference, args.reference_frame)
        write_report(report, rgb, args.output)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Target analysis failed: {exc}\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {(args.output / 'report.html').resolve()}")


if __name__ == "__main__":
    main()
