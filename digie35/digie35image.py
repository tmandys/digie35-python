#!/usr/bin/env python3

# vim: set expandtab:
# -*- coding: utf-8 -*-
#
# Copyright (c) 2025 MandySoft
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
__copyright__ = "Copyright (C) 2025 MandySoft"
__licence__ = "MIT"
__version__ = "0.1"

import logging
import time
import cv2
import numpy as np
import scipy as sp
import matplotlib.pyplot as plt

def show_image(img, name="Debug image"):
    cv2.imshow(name, img)
    while True:
        key = cv2.waitKey(100) & 0xFF
        if cv2.getWindowProperty(name, cv2.WND_PROP_VISIBLE) < 1:
            logging.getLogger().debug("Window closed by user")
            break
        if key == 27 or key == ord("q") or key == ord(" "):
            break

## Performance profiles
def log_duration(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        logging.getLogger().debug(f"{func.__name__}: {end-start:.3}s")
        return result
    return wrapper

## General error
class ImageAnalysisError(Exception):
    pass

class ImageAnalysis:
    _PERFORATION_HOLE_DISTANCE = 4.75 # mm
    _PERFORATION_HOLE_WIDTH = 1.98 # mm
    _FRAME_WIDTH = 36.5 # mm
    _FRAME_HEIGHT = _FRAME_WIDTH * 2 / 3
    _MAGNIFICATION = 0.95  # not 1:1 as we want borders
    # imagedata in BGR color space
    def __init__(self, image_data: bytes, filename = None):
        nparr = np.frombuffer(image_data, dtype=np.uint8)
        self._image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if self._image is None:
            raise ValueError("Wrong JPEG image")
        self._gray = cv2.cvtColor(self._image, cv2.COLOR_BGR2GRAY)
        h, w = self._gray.shape[:2]
        self._pixel_per_mm = w / self._FRAME_WIDTH / self._MAGNIFICATION
        self._filename = filename
        np.set_printoptions(threshold=np.inf)  # debug complete arrays
        self._reset()

    def _check_result(self, result):
        if isinstance(result, Exception):
            self._append_error(f"{type(result).__name__}: {str(result)}")
            return None
        else:
            logging.getLogger().debug(f"result: {result}")
            return result

    def _append_error(self, msg):
        self._errors.append(msg)
        logging.getLogger().error(msg)

    def _reset(self):
        self._errors = []
        self._result = {}
        self._status = None
        self._output_image = None
        if self._filename:
            self._result["filename"] = self._filename

    def _horiz_mm_to_px(self, mm, pixel_per_mm = None):
        if pixel_per_mm is None:
            h, w = self._gray.shape[:2]
            pixel_per_mm = w / self._FRAME_WIDTH / self._MAGNIFICATION
        return int(mm * pixel_per_mm)

    def _vert_mm_to_px(self, mm, pixel_per_mm = None):
        if pixel_per_mm is None:
            h, w = self._gray.shape[:2]
            pixel_per_mm = h / self._FRAME_HEIGHT / self._MAGNIFICATION
        return int(mm * pixel_per_mm)


    def _focus_score(self, region):
        laplacian = cv2.Laplacian(region, cv2.CV_64F)
        return laplacian.var()

    def xx__detect_perforation_holes(self, band):
        # najit contrastni tvary
        edges = cv2.Canny(band, 50, 150)
        show_image(edges)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
        #print(f"Kernel: {kernel}")
        # sloucit useky ktere patri ke stejne dire
        closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)
        #print(f"Closed: {closed}")

        # ziskat pozice der podle sirky (vyska bude urizla)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        perforation = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = w / h if h > 0 else 0
            area = cv2.contourArea(cnt)
            if 10 < w < 10:
                perforation.append((x, y, w, h))

        return perforation

    # profile is 1D array of analog values, region is array of [pos, width] to calculate statistic in profile
    # return array of [mean, std]
    def _calc_region_stat(self, profile, regions):
        values = []
        for x, w in regions:
            region = profile[x: x + w]
            if len(region) > 0:
                values.append([np.mean(region), np.std(region)])
            else:
                values.append([None, None])
        return np.array(values)

    # aggregated all regions
    def _calc_region_stat2(self, profile, regions):
        region = []
        for x, w in regions:
            region.extend(profile[x: x + w])
        if len(region) > 0:
            return (np.mean(region), np.std(region))
        else:
            return None

    def _calc_weighted_mean(self, mean1, count1, mean2, count2):
        cnt = 0
        sum = 0
        if mean1 is not None and count1 > 0:
            sum += mean1 * count1
            cnt += count1
        if mean2 is not None and count2 > 0:
            sum += mean2 * count2
            cnt += count2
        if cnt > 0:
            return sum / cnt
        else:
            return None

    @log_duration
    # global max. intensity and colormode
    def _analyze_overview(self):
        result = {}
        if len(self._image.shape) < 3 or self._image.shape[2] == 1:
            result["colormode"] = "bw"
        else:
            r = self._image[:, :, 0].astype(np.int16)
            g = self._image[:, :, 1].astype(np.int16)
            b = self._image[:, :, 2].astype(np.int16)

            diff_rg = np.abs(r - g)
            diff_gb = np.abs(g - b)
            diff_rb = np.abs(r - b)

            # get max diff for each pixel
            max_diff = np.maximum.reduce([diff_rg, diff_gb, diff_rb])
            # if majority of differences under threshold then BW
            perc = np.percentile(max_diff, 99)
            result["color_uniformity"] = perc
            result["colormode"] = "bw" if perc <= 8 else "color"

        max_intensity = np.percentile(self._gray, 99.5)  # avoid light artefacts
        result["naked_intensity"] = max_intensity

        # try detect how film is inserted, partially inserted film has frame start or end fully illuminated
        profile = np.mean(self._gray, axis = 0)
        # check leader and trailer naked ares
        film_start = 0
        film_end = len(profile)
        while film_start < film_end and profile[film_start] >= max_intensity * 0.95:
            film_start += 1
        while film_start < film_end and profile[film_end-1] >= max_intensity * 0.95:
            film_end -= 1

        result |= {
            "film_bounds": {"start": film_start, "end": film_end, },
        }
        return result

    @log_duration
    def _detect_perforation_holes(self, band, offsetx, name, **params):
        result = {}
        # show_image(band)
        # how many light pixels are above naked intensity
        result["naked_ratio"] = np.sum(band > params["naked_intensity"] * 0.95) / band.size
        if result["naked_ratio"] < 0.30:
            return ImageAnalysisError(f"Low {name} perforation naked ratio {result['naked_ratio']:.2f}, i.e. no holes on the edge")

        # hole is always ligher than film base even for negative so find peaks of intensity
        # we have 2D array where column should be uniform, i.e. hole or bridge
        # make 1D array averaging column value
        profile = np.mean(band, axis = 0)
        # ideally we have rectangle signal but in reality apply low-pass filter
        if True:
            profile = sp.ndimage.gaussian_filter1d(profile, sigma=2.0)
        else:
            window_size = 7
            kernel = np.ones(window_size) / window_size
            profile = np.convolve(profile, kernel, mode="same")

        # calculate mean value, variation
        mu = profile.mean()
        sigma = profile.std()
        cv = sigma / (mu +1e-6)

        if cv < 0.05:
            # low variability so no holes found
            return ImageAnalysisError(f"Low variability {cv:.3f} to detect {name} perforation")
        else:
            # adaptive threshold
            thr = mu + 0.3 * sigma
            # binarize, 1..hole, 0..bridge
            binary = profile > thr
            # find edges
            edges = np.diff(binary.astype(np.int8))
            # lo-hi
            starts = np.where(edges==1)[0]+1
            # hi-lo
            ends = np.where(edges==-1)[0]
            holes1 = []
            bridges1 = []
            hole_distances = []
            if len(starts) > 0 and len(ends) > 0:
                # we are interested inholes so array pair must start with lo->hi and end with hi->lo
                #print(f"starts{starts}, ends: {ends}")
                if starts[0] > ends[0]:
                    ends = np.delete(ends, 0)
                if len(ends) > 0:
                    if starts[-1] > ends[-1]:
                        starts = np.delete(starts, -1)
                centers = (starts + ends) // 2
                widths = ends-starts
                hole_width = self._horiz_mm_to_px(self._PERFORATION_HOLE_WIDTH)
                # get holes by expected width
                for idx in range(len(widths)):
                    if widths[idx] > hole_width / 2 and widths[idx] < hole_width * 1.1:
                        holes1.append([starts[idx], widths[idx]])

                # get bridges between neighbourgh holes
                def is_hole_dist_in_tolerance(dist):
                    return dist > hole_dist * 2 / 3 and dist < hole_dist * 1.1

                if len(holes1) > 1:
                    hole_dist = self._horiz_mm_to_px(self._PERFORATION_HOLE_DISTANCE)
                    edge = int((hole_dist - hole_width)*0.1)  # avoid edge to get more realistic film band intensity, i.e. not to confuse intensity gradient
                    for idx in range(len(holes1)-1):
                        dist = holes1[idx+1][0] - holes1[idx][0]
                        if is_hole_dist_in_tolerance(dist):
                            x = holes1[idx][0] + holes1[idx][1] + 1 + edge
                            w = holes1[idx+1][0] - x - 1 - edge
                            if w > 0:
                                bridges1.append([x, w])
                            hole_distances.append(dist)
                        else:
                            cnt = int(round(dist / hole_dist))
                            if cnt > 0:
                                dist2 = dist / cnt
                                if is_hole_dist_in_tolerance(dist2):
                                    hole_distances.append(dist2)

            if not len(holes1):
                return ImageAnalysisError(f"Cannot detect any {name} perforation hole")

            holes = np.array(holes1)
            bridges = np.array(bridges1)
            hole_stat = self._calc_region_stat2(profile, holes)
            bridge_stat = self._calc_region_stat2(profile, bridges)

            if hole_stat is not None and bridge_stat is not None:
                contrast = (hole_stat[0] - bridge_stat[0]) / (bridge_stat[0]+1)
            else:
                contrast = None

            if holes.size:
                if len(hole_distances) > 0:
                    w = np.array(hole_distances).mean()
                    pixel_per_mm = w / self._PERFORATION_HOLE_DISTANCE
                else:
                    w = np.mean(holes[:, 1])
                    pixel_per_mm = w / self._PERFORATION_HOLE_WIDTH
            else:
                pixel_per_mm = None

            if False:
                print(f"holes: {holes}/{hole_stat}, bridges: {bridges}/{bridge_stat}")

                plt.plot(binary)
                plt.plot(starts, binary[starts], "rx")
                plt.plot(ends, binary[ends], "bx")
                if holes.size:
                    plt.plot(holes[:, 0], binary[holes[:, 0]], "gx")
                if bridges.size:
                    plt.plot(bridges[:, 0], binary[bridges[:, 0]], "yx")
                plt.show()

            if offsetx != 0:
                for idx in range(len(holes1)):
                    holes1[idx][0] += offsetx
                for idx in range(len(bridges1)):
                    bridges1[idx][0] += offsetx
            result |= {
                #"uniformity": cv,
                "pixel_per_mm": pixel_per_mm,
                "contrast": contrast,
                "holes": {
                    "bounds": holes1,
                    "intensity": hole_stat[0] if hole_stat is not None else None,
                },
                "bridges": {
                    "bounds": bridges1,
                    "intensity": bridge_stat[0] if bridge_stat is not None else None,
                },
            }
            return result

    def _remove_spikes(self, arr):
        # remove spikes  0 0 0 1 -1 0 0 1 -1 0 0
        # print("_remove_spikes(%s)" % arr)
        for i in range(1, len(arr)-1):
            if arr[i-1] == 0 and arr[i] != 0 and arr[i] == -arr[i+1]:
                arr[i] = 0
                arr[i+1] = 0
        # print("_remove_spikes: %s" % arr)
        return arr


    @log_duration
    def _analyze_film_band(self, band, offsetx, name, **params):
        result = {}
        #show_image(band)
        # try detect how film is inserted, partially inserted film has frame start or end fully illuminated (as hole)
        # it might differ from inititial film_bound when film has non rectangular end
        # make 1D array averaging column value
        profile = np.mean(band, axis = 0)
        # profile = sp.ndimage.gaussian_filter1d(profile, sigma=2.0)
        thr = params["naked_intensity"] - (params["naked_intensity"] - params["film_base_intensity"]) * 0.05
        film_start = 0
        film_end = len(profile)
        while film_start < film_end and profile[film_start] >= thr:
            film_start += 1
        while film_start < film_end and profile[film_end-1] >= thr:
            film_end -= 1
        if film_start >= film_end - 1:
            return ImageAnalysisError(f"{name} band is naked")

        # cut off naked leader/trailer
        band = band[:, film_start:film_end]

        #show_image(band)

        # cross profile
        profile = np.mean(band, axis = 1)
        #profile = sp.ndimage.gaussian_filter1d(profile, sigma=2.0)
        thr = params["film_base_intensity"]
        thr_tol = max(thr * 0.02, 7)
        # signum 1 lighter, 0 band, -1 darker
        signum = np.zeros_like(profile, dtype=int)
        signum[profile > thr + thr_tol] = 1
        signum[profile < thr - thr_tol] = -1
        # find edges
        edges = np.diff(signum.astype(np.int8))
        edges = self._remove_spikes(edges)
        # remove spikes  0 0 0 1 -1 0 0 1 -1 0 0
        for i in range(1, len(edges)-1):
            if edges[i-1] == 0 and edges[i] != 0 and edges[i] == -edges[i+1]:
                edges[i] = 0
                edges[i+1] = 0
        changes = np.where(edges != 0)[0] + 1  # index to signum, edge is shifter by one
        if False:
            print(f"profile: {profile}, std: {profile.std()}, signum: {signum}, edges: {edges}, changes{changes}, [{thr-thr_tol}, {thr+thr_tol}]")
            plt.plot(signum)
            if changes.size:
                plt.plot(changes, signum[changes], "rx")
            plt.show()
        if signum[0] < 0:
            return ImageAnalysisError(f"{name} edge intensity bellow band")
        if len(changes) == 0:
            return ImageAnalysisError(f"{name} film band not detected")

        if signum[0] == 0:
            # no holes at the edge
            result |= {
                "negative": signum[changes[0]] < 0,
                "band_width": changes[0],
                "payload": True,
                "holes": False,
            }
        else:
            # perforation
            result["holes"] = True
            if signum[changes[0]] < 0:
                return ImageAnalysisError(f"{name} band is too dark")
            # band
            result["payload"] = len(changes) > 1
            if len(changes) > 1:
                result |= {
                    "negative": signum[changes[1]] < 0,
                    "band_width": changes[1],
                }
            else:
                result |= {
                    "negative": None,  # contrast ??
                    "band_width": changes[0],
                }
        if result["payload"] or result["holes"]:
            result["focus_score"] = self._focus_score(band)
        else:
            result["focus_score"] = None
        return result

    @log_duration
    def _detect_frame(self, payload, offsetx, **params):
        #show_image(payload)
        # cross film profile, gaps between frames should have approx.bridge intensity
        profile = np.mean(payload, axis = 0)
        sigma = np.std(payload, axis = 0)
        # ideally we have rectangle signal but in reality apply low-pass filter
        if True:
            profile = sp.ndimage.gaussian_filter1d(profile, sigma=2.0)
        else:
            window_size = 7
            kernel = np.ones(window_size) / window_size
            profile = np.convolve(profile, kernel, mode="same")

        # calculate mean value, variation
        mu = profile.mean()
        negative = params["film_base_intensity"] > mu   # double check with params["negative"]
        neg = params.get("negative", negative)
        if neg != negative:
            self._append_error("Confusing negative detection band vs. payload")
        # binarize, 0..gaps, 1..payload
        # gap should have film base intensity but it is not too robust, It should also have small variation, ideally zero
        # we cannot use relativa variation (sigma) and it soars in hights in dark band as we divide by small number
        # issue is that perforation film base intensity might be more centric than in midle of the strip so comparision fails
        if negative:
            gradient = (params["film_base_intensity"] - mu) * 0.01
            thr = params["film_base_intensity"] - gradient
        else:
            gradient = max((mu - params["film_base_intensity"]) * 0.05, 5)
            thr = params["film_base_intensity"] + gradient
        frames = []
        fl = False
        for idx in range(len(profile)):
            if negative:
                is_payload = (profile[idx] < thr) | (sigma[idx] > 8)
            else:
                is_payload = (profile[idx] > thr) | (sigma[idx] > 5)
            if is_payload != fl:
                if fl:
                    # avoid evidently wrong useless frames
                    if idx - start_pos > params["pixel_per_mm"]:
                        frames.append({"start": start_pos, "end": idx - 1})
                else:
                    start_pos = idx
                fl = not fl
        if fl:
            if idx - start_pos > params["pixel_per_mm"]:
                frames.append({"start": start_pos, "end": idx})

        confident_gradient = gradient * 5
        if len(frames) == 1:
            optimal_frame_width = self._FRAME_WIDTH * params["pixel_per_mm"]
            # low contast frames might be detected as too narrow

            #print(profile)
            fr = frames[0]
            #print(f"diff: {abs(profile[fr['start']] - params['film_base_intensity'])}, opt:{optimal_frame_width}")
            if fr["end"] - fr["start"] < optimal_frame_width and fr["start"] > 0 and fr["end"] < len(profile)-1:
                start_grad = abs(profile[fr["start"]+1] - profile[fr["start"]-1])
                end_grad = abs(profile[fr["end"]+1] - profile[fr["end"]-1])
                #print(f"grad{start_grad}/{end_grad}")
                if start_grad > confident_gradient:
                    #print(f"xx:{profile[fr['start']-offsetx]} diff: {profile[fr['start']-offsetx] - params['film_base_intensity']}")
                    #print("extend frame")
                    frames[0]["end"] = min(int(fr["start"] + optimal_frame_width), len(profile))
                elif end_grad > confident_gradient:
                    frames[0]["start"] = max(int(fr["end"] - optimal_frame_width), 0)
        elif len(frames) == 2:
            # we have 2 frames and we might extend payload in the middle, i.e. narrow gap
            optimal_frame_gap = max(int((self._gray.shape[1] - self._FRAME_WIDTH * params["pixel_per_mm"]) / 2), 0)
            #print(f"optimal_frame_gap:{optimal_frame_gap}")
            if frames[1]["start"] - frames[0]["end"] > optimal_frame_gap and frames[0]["start"] == 0 and frames[1]["end"] >= len(profile)-1:
                start_grad = abs(profile[frames[1]["start"]+1] - profile[frames[1]["start"]-1])
                end_grad = abs(profile[frames[0]["end"]+1] - profile[frames[0]["end"]-1])
                if start_grad > confident_gradient and end_grad < confident_gradient:
                    frames[0]["end"] = frames[1]["start"] - optimal_frame_gap
                elif end_grad > confident_gradient and start_grad < confident_gradient:
                    frames[1]["start"] = frames[0]["end"] + optimal_frame_gap

        for idx in range(len(frames)):
            frames[idx]["start"] += offsetx
            frames[idx]["end"] += offsetx
        if False:
            print(f"Profile:{profile}, sigma: {sigma}, bridge:{params['film_base_intensity']}, thr:{thr}, mu:{mu}, frames:{frames}")
            plt.plot(profile)
            plt.plot(sigma)

            plt.show()
        return {
            "frames": frames,
            "negative": negative,
            "payload_focus_score": self._focus_score(payload),
        }

    @log_duration
    def _calculate_move(self, **params):
        result = {}
        move_by = 0
        w = self._gray.shape[1]

        optimal_frame_width = self._FRAME_WIDTH * params["pixel_per_mm"]
        optimal_margin = max(int((w - optimal_frame_width) / 2), 0)
        minimal_margin = int(optimal_margin / 4)
        frames = params.get("frames", [])
        if frames:

            def center_frame(idx):
                frame_width = frames[idx]["end"] - frames[idx]["start"]
                frame_start_gap = frames[idx]["start"]
                frame_end_gap = w - frames[idx]["end"] - 1
                print(f"center: {idx}, frame_width: {frame_width}, start:{frame_start_gap}, end:{frame_end_gap}, minimal: {minimal_margin}, optimal:{optimal_frame_width}")
                if (frame_width >= optimal_frame_width or (frame_start_gap > 0 and frame_end_gap > 0)):
                    # we have at least full picture, slightly center to make some gap
                    # should work also in case of panorama when called recursively
                    if frame_end_gap < minimal_margin:
                        return -optimal_margin - frame_end_gap
                    elif frame_start_gap < minimal_margin:
                        return optimal_margin - frame_start_gap
                    else:
                        return 0
                elif frame_start_gap <= 0:
                    # there is partial picture we need make dicision how move
                    return max(frame_end_gap - optimal_margin, 0)
                else:
                    return -max(frame_start_gap - optimal_margin, 0)

            if len(frames) == 1:
                if frames[0]["start"] == 0 and frames[0]["end"] >= w - 1:
                    # we cannot move, frame is over whole picture
                    return ImageAnalysisError(f"No frame gap detected")
                move_by = center_frame(0)
            elif len(frames) == 2:
                move_by = center_frame(1 if frames[-1]["start"] < w / 2 or w - frames[-1]["end"] - 1 > 0 else 0)
            else:
                return ImageAnalysisError(f"Too many frames detected {len(frames)}")
        else:
            # no frame, so move by window width, in case of end of film will go beyond sensor
            move_by = w - minimal_margin

        result["move_by"] = move_by
        return result

    @log_duration
    def analyze(self):
        self._reset()
        self._result |= {
            "width": self._image.shape[1],
            "height": self._image.shape[0],
        }

        # preanalyze picture
        glob = self._check_result(self._analyze_overview())
        if glob:
            self._result |= glob

        fb = self._result["film_bounds"]
        if fb["end"] - fb["start"] < self._horiz_mm_to_px(self._PERFORATION_HOLE_DISTANCE):
            self._append_error(f"Film strip is not detected")
            self._status = "FILM_NOT_DETECTED"
            return

        # get top and buttom margin where we expect perforation, typical height should be around 27mm
        # holes crosses top/bottom edge of image as we want perforation in image as well
        margin1 = self._vert_mm_to_px(0.15)
        #dead = self._vert_mm_to_px(0.05)
        dead = 2
        top_perf = self._check_result(self._detect_perforation_holes(self._gray[dead:margin1, fb["start"]:fb["end"]], fb["start"], "top", **self._result))
        bottom_perf = self._check_result(self._detect_perforation_holes(self._gray[-margin1:-dead-1, fb["start"]:fb["end"]], fb["start"], "bottom", **self._result))

        if top_perf is None and bottom_perf is None:
            self._append_error(f"Cannot detect perforation")
            # as fallback try calc blindly focus score
            margin2 = self._vert_mm_to_px(3)
            self._result["band_focus_score"] = (self._focus_score(self._gray[dead:margin2, fb["start"]:fb["end"]]) + self._focus_score(self._gray[-margin2:-dead-1, fb["start"]:fb["end"]])) / 2
            self._status = "PERFORATION_NOT_DETECTED"
            return
        elif top_perf is None:
            self._result |= {
                "film_base_intensity": bottom_perf["bridges"]["intensity"],
                "naked_intensity": bottom_perf["holes"]["intensity"],
                "contrast": bottom_perf["contrast"],
                "pixel_per_mm": bottom_perf["pixel_per_mm"],
            }
        elif bottom_perf is None:
            self._result |= {
                "film_base_intensity": top_perf["bridges"]["intensity"],
                "naked_intensity": top_perf["holes"]["intensity"],
                "contrast": top_perf["contrast"],
                "pixel_per_mm": top_perf["pixel_per_mm"],
            }
        else:
            self._result |= {
                "film_base_intensity": self._calc_weighted_mean(top_perf["bridges"]["intensity"], len(top_perf["bridges"]["bounds"]), bottom_perf["bridges"]["intensity"], len(bottom_perf["bridges"]["bounds"])),
                "naked_intensity": self._calc_weighted_mean(top_perf["holes"]["intensity"], len(top_perf["holes"]["bounds"]), bottom_perf["holes"]["intensity"], len(bottom_perf["holes"]["bounds"])),
                "contrast": self._calc_weighted_mean(top_perf["contrast"], len(top_perf["holes"]["bounds"]), bottom_perf["contrast"], len(bottom_perf["holes"]["bounds"])),
                "pixel_per_mm": self._calc_weighted_mean(top_perf["pixel_per_mm"], len(top_perf["holes"]["bounds"]), bottom_perf["pixel_per_mm"], len(bottom_perf["holes"]["bounds"])),
            }

        def add_holes(name, perf, y1, y2):
            if not perf:
                return
            for hole in perf[name]["bounds"]:
                self._result[name].append((hole[0], y1, hole[0]+hole[1], y2))  # bounding box

        self._result["holes"] = []
        add_holes("holes", top_perf, dead, margin1)
        add_holes("holes", bottom_perf, self._result["height"]-margin1, self._result["height"]-dead)
        self._result["bridges"] = []
        add_holes("bridges", top_perf, dead, margin1)
        add_holes("bridges", bottom_perf, self._result["height"]-margin1, self._result["height"]-dead)

        if self._result["contrast"] is None:
            self._append_error(f"Cannot detect naked and film base intensity")
            self._status = "INTENSITY_ESTIMATION_FAILED"
            return

        margin2 = self._vert_mm_to_px(3, self._result["pixel_per_mm"])

        top_margin = self._check_result(self._analyze_film_band(self._gray[dead:margin2, fb["start"]:fb["end"]], fb["start"], "Top", **self._result))
        # flip vertically
        bottom_margin = self._check_result(self._analyze_film_band(self._gray[-dead-1:-margin2:-1, fb["start"]:fb["end"]], fb["start"], "Bottom", **self._result))
        if top_margin is None and bottom_margin is None:
            pass
        elif top_margin is None:
            self._result |= {
                "band_focus_score": bottom_margin["focus_score"],
                "negative": bottom_margin["negative"],
            }
        elif bottom_margin is None:
            self._result |= {
                "band_focus_score": top_margin["focus_score"],
                "negative": top_margin["negative"],
            }
        else:
            self._result |= {
                "band_focus_score": self._calc_weighted_mean(top_margin["focus_score"], 1, bottom_margin["focus_score"], 1),
            }
            if top_margin["negative"] == bottom_margin["negative"]:
                self._result["negative"] = top_margin["negative"]
            elif top_margin["negative"] is not None:
                self._result["negative"] = top_margin["negative"]
            else:
                self._result["negative"] = bottom_margin["negative"]

        y1 = top_margin["band_width"]+dead if top_margin else margin2
        y2 = bottom_margin["band_width"]+dead if bottom_margin else margin2
        self._result["band_width"] = {"top": y1, "bottom": y2}
        #print(f"fb:{fb}, y1:{y1}, y2:{y2}")
        frame = self._check_result(self._detect_frame(self._gray[y1:-y2, fb["start"]:fb["end"]], fb["start"], **self._result))
        if frame:
            self._result |= frame
            move = self._check_result(self._calculate_move(**self._result))
            if move is None:
                self._status = "UNDECIDABLE"
            else:
                self._status = "ALIGNED" if move["move_by"] == 0 else "SHIFT_REQUIRED"
                self._result |= move
        else:
            self._result = "FRAME_NOT_DETECTED"
        # TODO: get RGB from holes and analyze. It might help to detect BW vs. Color when non white LED is used

    def get_result(self):

        def round_floats(obj, digits=2):
            if isinstance(obj, float):
                return round(obj, digits)
            elif isinstance(obj, dict):
                return {k: round_floats(v, digits) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [round_floats(elem, digits) for elem in obj]
            else:
                return obj

        result = round_floats(self._result)
        result["status"] = self._status

        if len(self._errors):
            result["errors"] = self._errors
        return result

    def get_output_image(self):
        # BGR
        BLUE = (255, 0, 0)
        GREEN = (0, 255, 0)
        RED = (0, 0, 255)
        CYAN = (255, 255, 0)
        MAGENTA = (255, 0, 255)
        YELLOW = (0, 255, 255)
        WHITE = (255, 255, 255)
        BLACK = (0, 0, 0)
        GRAY = (127, 127, 127)

        result = self.get_result()

        if self._output_image is not None:
            return self._output_image
        out_image = self._image.copy()
        h, w = out_image.shape[:2]

        x = result.get("film_bounds", None)
        if x:
            cv2.line(out_image, (x["start"], 0), (x["start"], h), color=GREEN, thickness=2)
            cv2.line(out_image, (x["end"], 0), (x["end"], h), color=GREEN, thickness=2)

        band = result.get("band_width", None)
        if band:
            cv2.line(out_image, (0, band["top"]), (w, band["top"]), color=GREEN, thickness=2)
            cv2.line(out_image, (0, h-band["bottom"]), (w, h-band["bottom"]), color=GREEN, thickness=2)
        for frame in result.get("frames", []):
            cv2.rectangle(out_image, (frame["start"]+2, band["top"]+2), (frame["end"]-2, h-band["bottom"]-2), color=BLUE, thickness=2)

        holes = result.get("holes", [])
        for hole in holes:
            cv2.rectangle(out_image, (hole[0], hole[1]), (hole[2], hole[3]), color=MAGENTA, thickness=-1)

        holes = result.get("bridges", [])
        for hole in holes:
            cv2.rectangle(out_image, (hole[0], hole[1]), (hole[2], hole[3]), color=YELLOW, thickness=-1)

        move_by = result.get("move_by", 0)
        if move_by != 0 and move_by is not None:
            x1 = (w-move_by) if move_by > 0 else -move_by
            x2 = w if move_by > 0 else 0
            y = int(h/2)
            dy = 30
            pts = np.array([[x1, y-dy], [x1, y+dy], [x2, y]], np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.polylines(out_image, [pts], isClosed=True, color=BLACK, thickness=2)
            cv2.fillPoly(out_image, [pts], color=CYAN)

        txt_y = band["top"] + 20 if band else 50
        txt_x = 30

        def putText(s):
            nonlocal txt_y
            cv2.putText(out_image, s, (txt_x, txt_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, RED, 2)
            txt_y += 30

        putText(f"Size: {result['width']}x{result['height']}, Pixel/mm: {result.get('pixel_per_mm', None)}")
        putText(f"Color mode: {result.get('colormode', None)} ({result.get('color_uniformity', None)}), Negative: {result.get('negative', None)}")
        putText(f"Film base: {result.get('film_base_intensity', None)}, Naked: {result.get('naked_intensity', None)}, Contrast: {result.get('contrast', None)}")
        putText(f"Focus score: Band: {result.get('band_focus_score', None)}, Payload: {result.get('payload_focus_score', None)}")
        move_by = result.get("move_by", None)
        if move_by is None:
            putText(f"Status: {result.get('status', None)}")
        else:
            putText(f"Status: {result.get('status', None)}, Move by: {move_by}")
        for err in result.get("errors", []):
            putText(err)

        self._output_image = out_image
        return out_image
