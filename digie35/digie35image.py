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
import json

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        return super().default(obj)

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
    _PERFORATION_HOLE_DISTANCE2 = 25.5 # mm
    _FRAME_WIDTH = 36.5 # mm
    _FRAME_HEIGHT = _FRAME_WIDTH * 2 / 3
    _MAGNIFICATION = _FRAME_HEIGHT / (_FRAME_HEIGHT + 1.2)  # not 1:1 as we want perforation
    # imagedata in BGR color space
    def __init__(self, image_data: bytes, filename = None):
        nparr = np.frombuffer(image_data, dtype=np.uint8)
        self._image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if self._image is None:
            raise ValueError("Wrong JPEG image")
        h, w = self._image.shape[:2]
        self._pixel_per_mm = h / self._FRAME_HEIGHT * self._MAGNIFICATION
        #print(f"Image: {w}x{h}, ratio: {self._pixel_per_mm}, Frame: {self._FRAME_WIDTH}x{self._FRAME_HEIGHT}, Magnify: {self._MAGNIFICATION}")
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
            pixel_per_mm = w / self._FRAME_WIDTH * self._MAGNIFICATION
        return int(mm * pixel_per_mm)

    def _vert_mm_to_px(self, mm, pixel_per_mm = None):
        if pixel_per_mm is None:
            h, w = self._gray.shape[:2]
            pixel_per_mm = h / self._FRAME_HEIGHT * self._MAGNIFICATION
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
        #print(f"weight: {mean1}/{count1}+{mean2}/{count2}")
        cnt = 0
        sum = 0
        if mean1 is not None and count1 is not None and count1 > 0:
            sum += mean1 * count1
            cnt += count1
        if mean2 is not None and count2 is not None and count2 > 0:
            sum += mean2 * count2
            cnt += count2
        if cnt > 0:
            result = sum / cnt
        else:
            result = None
        #print(f"Result: {result}")
        return result

    @log_duration
    # global max. intensity and colormode
    def _analyze_overview(self):
        """
            Returns:
                color_uniformity: low value is low diff between RGB, i.e. gray scale
                color_mode: (bw, color)
                naked_intensity ... maximum intensity in image

        """
        result = {}
        if len(self._image.shape) < 3 or self._image.shape[2] == 1:
            result["color_mode"] = "bw"
            self._gray = self._image
        else:
            b, g, r = cv2.split(self._image)
            #r = self._image[:, :, 0].astype(np.int16)
            #g = self._image[:, :, 1].astype(np.int16)
            #b = self._image[:, :, 2].astype(np.int16)

            diff_rg = np.abs(r - g)
            diff_gb = np.abs(g - b)
            diff_rb = np.abs(r - b)

            # get max diff for each pixel
            max_diff = np.maximum.reduce([diff_rg, diff_gb, diff_rb])
            # if majority of differences under threshold then BW
            perc = np.percentile(max_diff, 99)
            result["color_uniformity"] = perc
            # select channel with max. variability, even for gray scale it is not bottleneck vs. self._gray = cv2.cvtColor(self._image, cv2.COLOR_BGR2GRAY)
            # variability of gray scale is always lower than any separate channel
            stds = [b.std(), g.std(), r.std()]
            self._gray = [b, g, r][np.argmax(stds)]
            #print(f"BGR[{np.argmax(stds)}, stds: {stds}")
            result["color_mode"] = "bw" if perc <= 8 else "color"
            #show_image(b)
            #show_image(g)
            #show_image(r)

        #print(f"Color mode: {result['color_mode']}, perc: {perc}, bgr: {np.argmax(stds)}")
        #show_image(self._gray)

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
    def _detect_dead_margin(self, band, name, **params):
        """
        Detect artifacts on the film edge, typically dark stripes caused by unilluminated black margin.
        When film is misaaligned then top and bottom perforation is not equal. And win worser case when
        film is not paralell to adapter then perforation is skewed and contains diagonal edge black stripe.
        If the perforation holes are narrow then we cannot detect horizontally hole/bridge ratio. We could
        improve algorithm by dividing perforation vertically and inspecting per partes. Not implemented
        because another perforation should be wider and easy to inspect.
        """
        dead = 0
        #show_image(band)
        dark_artifacts = np.percentile(band, 5)
        mu = band[band >= dark_artifacts].mean()
        #print(f"dark artifacts: {dark_artifacts}, mu:{mu}")
        w = max(0.4, 1-(params['naked_intensity'] - mu)/30)   # weighted average when small distance the use weight on naked otherwise use average
        thr = int(params['naked_intensity']*w + mu * (1-w))
        for row in band:
            naked_ratio = np.count_nonzero(row >= thr) / row.size
            #naked_ratio = np.sum(row > params["naked_intensity"] * 0.94) / row.size
            #print(f"dead: {dead}, row: {row}, thr: {thr}, naked: {naked_ratio}, naked: {params['naked_intensity']}")
            if naked_ratio > 0.33:
                return dead
            dead += 1
        # TODO: fallback when band is clear then decrease naked ratio as it might be hole at innermost distance where ration is 25% or so
        #show_image(band)
        return None

    @log_duration
    def _detect_perforation_holes(self, band, offsetx, name, **params):
        result = {}
        #show_image(band)
        # how many light pixels are above naked intensity
        if False:
            print(f"Band: {band}, naked: {params['naked_intensity']}")
        #result["naked_ratio"] = np.count_nonzero(band > params["naked_intensity"] * 0.95) / band.size
        #if result["naked_ratio"] < 0.30:
        #    return ImageAnalysisError(f"Low {name} perforation naked ratio {result['naked_ratio']:.2f}, i.e. no holes on the edge")

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
        cv = sigma / (mu + 1e-6)
        if False:
            print(f"mu:{mu}, sigma:{sigma}, cv:{cv}")
        # adaptive threshold
        # for light bridges and some dust/demage average is beyond hole/bridge interval
        # and for nice contrast perforation might fall test to two major values to detect bridge/hole because both might be in bridge (or hole) so decrease bin count
        perc5, perc95 = np.percentile(band, [5, 95])
        contrast_range = perc95 - perc5
        # normalize 0-1 by 255
        norm_contrast = np.clip(contrast_range / 255, 0, 1)

        MIN_BINS = 2
        MAX_BINS = 64
        GAMMA = 1.2   # non linear to start rising slowly
        norm_contrast = norm_contrast ** GAMMA
        bin_count = int(round(MAX_BINS - norm_contrast * (MAX_BINS - MIN_BINS)))       # adaptive between 4 - 64 bins
        bin_count = max(MIN_BINS, bin_count)

        #thr = mu + 0.3 * sigma
        # so calculate histogram
        hist, bins = np.histogram(profile, bins=bin_count, range=(0, 256))
        indices = np.argsort(hist)[::-1] # sort desc, first two items should contain hole&bridge
        top_bins = indices[:2]   # two peaks
        thr = (bins[indices[0]+1]+bins[indices[1]+1]+bins[indices[0]]+bins[indices[1]]) / 4
        if False:
            print(f"mu: {mu}, sigma: {sigma}, thr: {thr}, indices: {indices}, top_bins: {top_bins}, hist: {hist}, bins: {bins}, perc5: {perc5}, perc95: {perc95}, norm_contrast: {norm_contrast}, bincount: {bin_count}")
            #print(f"band: {band}, profile: {profile}")

        # binarize, 1..hole, 0..bridge
        binary = profile > thr
        # find edges
        edges = np.diff(binary.astype(np.int8))
        # lo-hi
        starts = np.where(edges==1)[0]+1
        # hi-lo
        ends = np.where(edges==-1)[0]
        if False:
            print(f"edges: {edges}, starts: {starts}, ends: {ends}")
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

        if len(holes1):
            holes = np.array(holes1)
            bridges = np.array(bridges1)
            hole_stat = self._calc_region_stat2(profile, holes)
            bridge_stat = self._calc_region_stat2(profile, bridges)

            if hole_stat is not None and bridge_stat is not None:
                contrast = (hole_stat[0] - bridge_stat[0]) / (bridge_stat[0]+1)
            else:
                contrast = None

            pixel_per_mm = 0
            #print(f"hole_distances:{hole_distances}, holes:{holes}")
            if len(holes):
                if len(hole_distances) > 0:
                    w = np.array(hole_distances).mean()
                    pixel_per_mm = w / self._PERFORATION_HOLE_DISTANCE
                    resolution_weight = 2 * len(hole_distances)
                else:
                    w = np.mean(holes[:, 1])
                    pixel_per_mm = w / self._PERFORATION_HOLE_WIDTH
                    resolution_weight = len(holes)
            if pixel_per_mm < self._pixel_per_mm * 0.8:  # hole width tends provide misleading sizes
                pixel_per_mm = self._pixel_per_mm   # fallback
                resolution_weight = 0.1

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
                "resolution_weight": resolution_weight,
                "base_weight": len(bridges1),
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
        elif params["naked_intensity"] >= 255:  # burnt perforation holes
            result |= {
                #"uniformity": cv,
                "pixel_per_mm": self._pixel_per_mm,
                "resolution_weight": 0.1,
                "base_weight": 1,
                "contrast": 0,
                "holes": {
                    "bounds": [],
                    "intensity": params["naked_intensity"],
                },
                "bridges": {
                    "bounds": [],
                    "intensity": params["naked_intensity"],
                },
            }
        else:
            return ImageAnalysisError(f"Cannot detect any {name} perforation hole")
        return result

    @log_duration
    def _detect_hole_depth(self, band, perf, name, **params):
        result = []
        #print(f"params:{params}")
        thr = (params["film_base_intensity"]+params["naked_intensity"]) / 2 
        for hole in perf["holes"]["bounds"]:
            depth = 0
            for row in band:
                mu = np.mean(row[hole[0]:hole[0]+hole[1]])
                depth += 1
                if mu <= thr:
                    break
            result.append(depth)
        return result

    @log_duration
    def _calculate_mean_value(self, band, bounds, **params):
        #print(f"Bounds: {bounds}")
        if len(bounds) == 0:
            return None
        #show_image(band)
        sum = 0
        for x, w in (bounds):
            sum += np.mean(band[:, x:x+w])
        return sum / len(bounds)


    def _remove_spikes(self, arr):
        # remove spikes  0 0 0 1  0 0 1 -1 0 0  > 0 0 0 0 0 0 1 -1 0 0
        # print("_remove_spikes(%s)" % arr)
        for i in range(1, len(arr)-1):
            if arr[i-1] != arr[i] and arr[i-1] == arr[i+1]:
                arr[i] = arr[i-1]
        # print("_remove_spikes: %s" % arr)
        return arr


    @log_duration
    def _analyze_film_band(self, band, offsetx, name, **params):
        """
            band ... ideally bare band because holes should be skipped.
        """
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
        result |= {
            "start": film_start + offsetx,
            "end": film_end + offsetx,
        }

        # cut off naked leader/trailer
        band = band[:, film_start:film_end]

        #show_image(band)

        # cross profile
        profile = np.mean(band, axis = 1)
        #profile = sp.ndimage.gaussian_filter1d(profile, sigma=2.0)
        #print(f"Params:{params}, profile: {profile}")
        thr = params["film_base_intensity"]
        thr_tol = max(thr * 0.02, 7)
        # signum 1 lighter, 0 band, -1 darker
        signum = np.zeros_like(profile, dtype=int)
        signum[profile > thr + thr_tol] = 1
        signum[profile < thr - thr_tol] = -1
        # if supposed negative then remove leading dark artifacts
        if signum[-1] == -1:
            for i in range(0, 4):
                if signum[i] == -1:
                    signum[0] = signum[i+1]
                else:
                    break
        # remove leading change
        if len(signum) > 3:
            if signum[0] != 0 and signum[1] == 0 and signum[2] == 0:
                signum[0] = 0
        signum = self._remove_spikes(signum)
        # find edges
        edges = np.diff(signum.astype(np.int8))
        changes = np.where(edges != 0)[0] + 1  # index to signum, edge is shifter by one
        if False:
            print(f"profile: {profile}, std: {profile.std()}, signum: {signum}, edges: {edges}, changes{changes}, [{thr-thr_tol}, {thr+thr_tol}]")
            plt.plot(signum)
            if changes.size:
                plt.plot(changes, signum[changes], "rx")
            plt.show()
        if len(changes) == 0:
            return ImageAnalysisError(f"{name} film band not detected")
        # no holes at the edge, value in expected value
        result |= {
            "negative": edges[changes[0]-1] < 0,
            "band_width": changes[0],
            "payload": True,
        }
        if result["payload"]:
            result["focus_score"] = self._focus_score(band)
        else:
            result["focus_score"] = None
        result["film_base_intensity"] = np.mean(profile[0: result["band_width"]-1]) if result["band_width"] > 1 else None
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
            #print(f"mu:{mu} < film_base: {params['film_base_intensity']}, neg: {neg}")
            self._append_error("Confusing negative detection band vs. payload")
        # binarize, 0..gaps, 1..payload
        # gap should have film base intensity but it is not too robust, It should also have small variation, ideally zero
        # we cannot use relativa variation (sigma) and it soars in hights in dark band as we divide by small number
        # issue is that perforation film base intensity might be more centric than in midle of the strip so comparision fails
        if negative:
            gradient = max((params["film_base_intensity"] - mu) * 0.01, 5)
            thr = params["film_base_intensity"] - gradient
            thr_sigma = 8
        else:
            gradient = max((mu - params["film_base_intensity"]) * 0.05, 5)
            thr = params["film_base_intensity"] + gradient
            thr_sigma = 5
        frames = []
        #print(f"Profile: {profile}, sigma: {sigma}, negative: {negative}, thr: {thr}, Filmbase: {params['film_base_intensity']}")
        fl = False
        for idx in range(len(profile)):
            if negative:
                is_payload = (profile[idx] < thr) | (sigma[idx] > thr_sigma)
            else:
                is_payload = (profile[idx] > thr) | (sigma[idx] > thr_sigma)
            if is_payload != fl:
                if fl:
                    # avoid evidently wrong useless frames, e.g. 1mm
                    if idx - start_pos > params["pixel_per_mm"]*1:
                        frames.append({"start": start_pos, "end": idx - 1})
                else:
                    start_pos = idx
                fl = not fl
        if fl:
            if idx - start_pos > params["pixel_per_mm"]:
                frames.append({"start": start_pos, "end": idx})

        # print(f"Frames: {frames}")
        # now try do a heuristic to optimize non contarast frames
        optimal_frame_width = self._FRAME_WIDTH * params["pixel_per_mm"]

        def extend_frame(fr, min_x, max_x, thr_sigma):
            while fr["end"] - fr["start"] < optimal_frame_width:
                if fr["start"] > min_x and fr["end"] < max_x:
                    start_grad = abs(profile[fr["start"]+1] - profile[fr["start"]-1])
                    end_grad = abs(profile[fr["end"]+1] - profile[fr["end"]-1])
                    if start_grad < end_grad and sigma[fr["start"]] >= thr_sigma:
                        fr["start"] -= 1
                    elif start_grad > end_grad and sigma[fr["end"]] >= thr_sigma:
                        fr["end"] += 1
                    elif sigma[fr["start"]] > sigma[fr["end"]] and sigma[fr["start"]] >= thr_sigma:
                        fr["start"] -= 1
                    elif sigma[fr["start"]] < sigma[fr["end"]] and sigma[fr["end"]] >= thr_sigma:
                        fr["end"] += 1
                    else:
                        break
                elif fr["start"] > min_x:
                    if sigma[fr["start"]] >= thr_sigma:
                        fr["start"] -= 1
                    else:
                        break
                elif fr["end"] < max_x:
                    if sigma[fr["end"]] >= thr_sigma:
                        fr["end"] += 1
                    else:
                        break
                else:
                    break
            return fr["start"] == min_x or fr["end"] == max_x

        def shrink_gap(fr1, fr2, thr_sigma):
            if fr2["end"] - fr1["start"] < optimal_frame_width * 1.05:
                min_gap = 0
            else:
                # won't join to longer picture than optimal, apoparently 2 separate pictures
                min_gap = max(int((params["width"] - optimal_frame_width) / 2), 0)
            while fr2["start"] - fr1["end"] > min_gap:
                start_grad = abs(profile[fr1["end"]+1] - profile[fr1["end"]-1])
                end_grad = abs(profile[fr2["start"]+1] - profile[fr2["start"]-1])
                #print(f"shrink: end: {fr1['end']}, start: {fr2['start']}, grad: {start_grad}/{end_grad}")
                if start_grad < end_grad and sigma[fr1["end"]] >= thr_sigma:
                    fr1["end"] += 1
                elif start_grad > end_grad and sigma[fr2["start"]] >= thr_sigma:
                    fr2["start"] -= 1
                elif sigma[fr1["end"]] > sigma[fr2["start"]] and sigma[fr1["end"]] >= thr_sigma:
                    fr1["end"] += 1
                elif sigma[fr1["end"]] < sigma[fr2["start"]] and sigma[fr2["start"]] >= thr_sigma:
                    fr2["start"] -= 1
                else:
                    break
            return fr1["end"] >= fr2["start"]-1   # merge frames

        def shrink_frame(fr, thr_sigma):
            while fr["end"] - fr["start"] > optimal_frame_width:
                if sigma[fr["start"]] < sigma[fr["end"]] and sigma[fr["start"]] < thr_sigma:
                    fr["start"] += 1
                elif sigma[fr["start"]] > sigma[fr["end"]] and sigma[fr["end"]] < thr_sigma:
                    fr["end"] -= 1
                else:
                    break

        thr_sigma2 = thr_sigma / 2   # not to extend frames in gap

        if len(frames) > 2:
            # physically max two frames of normal width so likely we need merge
            idx = 0
            while idx < len(frames)-1:
                if shrink_gap(frames[idx], frames[idx+1], thr_sigma2):
                    del frames[idx+1]
                else:
                    idx += 1

        if len(frames) == 1:
            # low contast frames might be detected as too narrow

            #print(profile)
            #print(f"diff: {abs(profile[frames[0]['start']] - params['film_base_intensity'])}, opt:{optimal_frame_width}")
            if not extend_frame(frames[0], 0, len(profile)-1, thr_sigma2):
                # if payload does not touch limit then it is likely extendable, so try once more with looser sigma
                extend_frame(frames[0], 0, len(profile)-1, thr_sigma2/4)
            shrink_frame(frames[0], thr_sigma2)
        elif len(frames) == 2:
            # we have 2 frames and we might extend payload in the middle, i.e. narrow gap
            if shrink_gap(frames[0], frames[1], thr_sigma2):
                frames[0]["end"] = frames[1]["end"]
                del frames[1]
                if not extend_frame(frames[0], 0, len(profile)-1, thr_sigma2):
                    extend_frame(frames[0], 0, len(profile)-1, thr_sigma2/2)
            elif frames[0]["start"] > 0 and frames[1]["end"] < len(profile)-1 and abs(frames[1]["end"] - frames[0]["start"] - optimal_frame_width) < optimal_frame_width * 0.1:
                # likely two joinable frames, try harder
                if shrink_gap(frames[0], frames[1], thr_sigma2/4):
                    frames[0]["end"] = frames[1]["end"]
                    del frames[1]
                    extend_frame(frames[0], 0, len(profile)-1, thr_sigma2/2)

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
                #print(f"center: {idx}, frame_width: {frame_width}, start:{frame_start_gap}, end:{frame_end_gap}, minimal: {minimal_margin}, optimal:{optimal_frame_width}, optimal_margin:{optimal_margin}, pixel_per_mm:{params['pixel_per_mm']}")
                if (frame_width >= optimal_frame_width or (frame_start_gap > 0 and frame_end_gap > 0)):
                    # we have at least full picture, slightly center to make some gap
                    # should work also in case of panorama when called recursively
                    if frame_end_gap < minimal_margin or frame_start_gap < minimal_margin:
                        return int((frame_start_gap + frame_end_gap) / 2) - frame_start_gap
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
                #print(f"w: {w}, frames[-1]: {frames[-1]['start']}-{frames[-1]['end']}")
                move_by = center_frame(1 if frames[-1]["start"] < w / 2 or w - frames[-1]["end"] - 1 > 0 or frames[-1]["end"] - frames[-1]["start"] > frames[0]["end"] - frames[0]["start"] else 0)
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
        margin0 = self._vert_mm_to_px(1)
        #top_dead = self._vert_mm_to_px(0.05)
        top_dead = self._check_result(self._detect_dead_margin(self._gray[0:margin0, fb["start"]:fb["end"]], "top", **self._result))
        bottom_dead = self._check_result(self._detect_dead_margin(self._gray[-1:-margin0-1:-1, fb["start"]:fb["end"]], "top", **self._result))

        # margin1 = self._vert_mm_to_px(0.15)
        margin1 = 1
        top_perf = self._check_result(self._detect_perforation_holes(self._gray[top_dead:top_dead+margin1, fb["start"]:fb["end"]], fb["start"], "top", **self._result)) if not top_dead is None else None
        bottom_perf = self._check_result(self._detect_perforation_holes(self._gray[-bottom_dead-1:-bottom_dead-margin1-1:-1, fb["start"]:fb["end"]], fb["start"], "bottom", **self._result)) if not bottom_dead is None else None
        if top_dead is None:
            top_dead = 0
        if bottom_dead is None:
            bottom_dead = 0
        resolution_weight = None
        if top_perf is None and bottom_perf is None:
            self._append_error(f"Cannot detect perforation")
            # as fallback try calc blindly focus score
            margin2 = self._vert_mm_to_px(3)
            self._result["band_focus_score"] = (self._focus_score(self._gray[top_dead:top_dead+margin2, fb["start"]:fb["end"]]) + self._focus_score(self._gray[-margin2-bottom_dead-1:-bottom_dead-1, fb["start"]:fb["end"]])) / 2
            self._status = "PERFORATION_NOT_DETECTED"
            return
        elif top_perf is None:
            self._result |= {
                "film_base_intensity": bottom_perf["bridges"]["intensity"],
                "naked_intensity": bottom_perf["holes"]["intensity"],
                "contrast": bottom_perf["contrast"],
                "pixel_per_mm": bottom_perf["pixel_per_mm"],
            }
            resolution_weight = bottom_perf["resolution_weight"]
        elif bottom_perf is None:
            self._result |= {
                "film_base_intensity": top_perf["bridges"]["intensity"],
                "naked_intensity": top_perf["holes"]["intensity"],
                "contrast": top_perf["contrast"],
                "pixel_per_mm": top_perf["pixel_per_mm"],
            }
            resolution_weight = top_perf["resolution_weight"]
        else:
            self._result |= {
                "film_base_intensity": self._calc_weighted_mean(top_perf["bridges"]["intensity"], top_perf["base_weight"], bottom_perf["bridges"]["intensity"], bottom_perf["base_weight"]),
                "naked_intensity": self._calc_weighted_mean(top_perf["holes"]["intensity"], len(top_perf["holes"]["bounds"])+0.0001, bottom_perf["holes"]["intensity"], len(bottom_perf["holes"]["bounds"])+0.0001),
                "contrast": self._calc_weighted_mean(top_perf["contrast"], top_perf["base_weight"], bottom_perf["contrast"], bottom_perf["base_weight"]),
                "pixel_per_mm": self._calc_weighted_mean(top_perf["pixel_per_mm"], top_perf["resolution_weight"], bottom_perf["pixel_per_mm"], bottom_perf["resolution_weight"]),
            }
            resolution_weight = self._calc_weighted_mean(top_perf["resolution_weight"], 1, bottom_perf["resolution_weight"], 1)

        margin2 = self._vert_mm_to_px(3, self._result["pixel_per_mm"])
        self._result["holes"] = []
        # hole depth needed to skip film edge if possible where might be light artefacts
        top_depth = -1
        bottom_depth = -1
        if not self._result["contrast"] is None:   # base intensity is mandatory
            top_base_intensity = None
            if top_perf:
                depths = self._check_result(self._detect_hole_depth(self._gray[top_dead:top_dead+margin2, :], top_perf, "top", **self._result))
                for idx, hole in enumerate(top_perf["holes"]["bounds"]):
                    self._result["holes"].append((hole[0], top_dead, hole[0]+hole[1], top_dead+depths[idx]))  # bounding box
                    if depths[idx] > top_depth:
                        top_depth = depths[idx]   # add some pixels as hole border can provide a shade
                if top_depth >= 0:
                    top_base_intensity = self._check_result(self._calculate_mean_value(self._gray[top_dead:top_dead+top_depth, :], top_perf["bridges"]["bounds"], **self._result))
            bottom_base_intensity = None
            if bottom_perf:
                depths = self._check_result(self._detect_hole_depth(self._gray[-bottom_dead-1:-bottom_dead-margin2-1:-1, :], bottom_perf, "bottom", **self._result))
                for idx, hole in enumerate(bottom_perf["holes"]["bounds"]):
                    self._result["holes"].append((hole[0], self._result["height"]-depths[idx]-bottom_dead, hole[0]+hole[1], self._result["height"]-bottom_dead))  # bounding box
                    if depths[idx] > bottom_depth:
                        bottom_depth = depths[idx]   # dtto
                if bottom_depth >= 0:
                    bottom_base_intensity = self._check_result(self._calculate_mean_value(self._gray[-bottom_dead-1:-bottom_dead-bottom_depth-1:-1, :], bottom_perf["bridges"]["bounds"], **self._result))
            if not top_base_intensity is None or not bottom_base_intensity is None:
                self._result["film_base_intensity"] = self._calc_weighted_mean(top_base_intensity, top_perf.get("base_weight") if top_perf else None, bottom_base_intensity, bottom_perf.get("base_weight") if bottom_perf else None)

        calc_vert_res = top_depth >= 0 and bottom_depth >= 0
        top_depth = max(0, top_depth) + top_dead
        bottom_depth = max(0, bottom_depth) + bottom_dead
        if calc_vert_res:
            # top and bottom holes found so we can calc dpi as vertical distance is known
            pixel_per_mm = (self._result["height"] - top_depth - bottom_depth) / self._PERFORATION_HOLE_DISTANCE2
            # print(f"Vertical pixel_per_mm: {pixel_per_mm}")
            self._result["pixel_per_mm"] = self._calc_weighted_mean(self._result["pixel_per_mm"], resolution_weight, pixel_per_mm, 3)
            resolution_weight += 3
        def add_holes(name, perf, y1, y2):
            if not perf:
                return
            for hole in perf[name]["bounds"]:
                self._result[name].append((hole[0], y1, hole[0]+hole[1], y2))  # bounding box

        #add_holes("holes", top_perf, top_dead, margin1)
        #add_holes("holes", bottom_perf, self._result["height"]-margin1, self._result["height"]-bottom_dead)
        self._result["bridges"] = []
        if top_perf:
            add_holes("bridges", top_perf, top_dead, margin1)
        if bottom_perf:
            add_holes("bridges", bottom_perf, self._result["height"]-margin1, self._result["height"]-bottom_dead)

        if self._result["contrast"] is None:
            self._append_error(f"Cannot detect naked and film base intensity")
            self._status = "INTENSITY_ESTIMATION_FAILED"
            return

        top_margin = self._check_result(self._analyze_film_band(self._gray[top_depth:top_depth+margin2, fb["start"]:fb["end"]], fb["start"], "Top", **self._result))
        # flip vertically
        bottom_margin = self._check_result(self._analyze_film_band(self._gray[-bottom_depth-1:-bottom_depth-margin2-1:-1, fb["start"]:fb["end"]], fb["start"], "Bottom", **self._result))
        if top_margin is None and bottom_margin is None:
            pass
        elif top_margin is None:
            self._result |= {
                "band_focus_score": self._focus_score(self._gray[-bottom_depth-bottom_margin["band_width"]-1:-bottom_dead-1, bottom_margin["start"]:bottom_margin["end"]]),
                "negative": bottom_margin["negative"],
                "film_base_intensity": self._calc_weighted_mean(self._result["film_base_intensity"], 1, bottom_margin["film_base_intensity"], 1)
            }
        elif bottom_margin is None:
            self._result |= {
                "band_focus_score": self._focus_score(self._gray[top_dead:top_depth+top_margin["band_width"], top_margin["start"]:top_margin["end"]]),
                "negative": top_margin["negative"],
                "film_base_intensity": self._calc_weighted_mean(self._result["film_base_intensity"], 1, top_margin["film_base_intensity"], 1)
            }
        else:
            pixel_per_mm = (self._result["height"] - top_depth - bottom_depth - top_margin["band_width"] - bottom_margin["band_width"]) / self._FRAME_HEIGHT
            if (pixel_per_mm - self._pixel_per_mm) / self._pixel_per_mm > 0.2:  # band width depends on image
                    pixel_per_mm = None
            self._result |= {
                "band_focus_score": self._calc_weighted_mean(
                    self._focus_score(self._gray[top_dead:top_depth+top_margin["band_width"], top_margin["start"]:top_margin["end"]]), top_margin["band_width"],
                    self._focus_score(self._gray[-bottom_depth-bottom_margin["band_width"]-1:-bottom_dead-1, bottom_margin["start"]:bottom_margin["end"]]), bottom_margin["band_width"]
                ),
                "film_base_intensity": self._calc_weighted_mean(self._result["film_base_intensity"], 1,
                    self._calc_weighted_mean(top_margin["film_base_intensity"], top_margin["band_width"], bottom_margin["film_base_intensity"], bottom_margin["band_width"])
                    , 2),
                "pixel_per_mm": self._calc_weighted_mean(self._result["pixel_per_mm"], resolution_weight, pixel_per_mm, 3)
            }
            if top_margin["negative"] == bottom_margin["negative"]:
                self._result["negative"] = top_margin["negative"]
            elif top_margin["negative"] is not None:
                self._result["negative"] = top_margin["negative"]
            else:
                self._result["negative"] = bottom_margin["negative"]

        y1 = top_margin["band_width"]+top_depth if top_margin else margin2
        y2 = bottom_margin["band_width"]+bottom_depth if bottom_margin else margin2
        self._result["band_width"] = {"top": y1, "bottom": y2}
        #print(f"fb:{fb}, y1:{y1}, y2:{y2}")
        frame = self._check_result(self._detect_frame(self._gray[y1:-y2, fb["start"]:fb["end"]], fb["start"], **self._result))
        if frame:
            self._result |= frame
            move = self._check_result(self._calculate_move(**self._result))
            if move is None:
                self._status = "UNDETERMINATE"
            else:
                self._status = "ALIGNED" if move["move_by"] == 0 else "SHIFT_REQUIRED"
                self._result |= move
        else:
            self._result = "FRAME_NOT_DETECTED"
        # TODO: get RGB from holes and analyze. It might help to detect BW vs. Color when non white LED is used

    @log_duration
    def analyze_rgb_intensity(self, roi_fraction = 0.2):
        """
            Calculate center image intensity in RGB channels to calibrate RGB LEDs
            Args:
                roi_fraction (float): crop size (0-1)

            Returns:
                tuple: (R_mean, G_mean, B_mean)
        """
        img_rgb = cv2.cvtColor(self._image, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]
        roi_w = int(w * roi_fraction)
        roi_h = int(h * roi_fraction)
        x0 = w // 2 - roi_w // 2
        y0 = h // 2 - roi_h // 2
        roi = img_rgb[y0:y0+roi_h, x0:x0+roi_w]
        mean_rgb = np.mean(roi, axis=(0, 1))
        #print(f"RGB: {mean_rgb}")
        return tuple(mean_rgb)

    @log_duration
    def analyze_uniformity(self, grid=10):
        """
        Analyze illumination intensity
        Args:
            grid (int): matrix size

        Returns:
            uniformity: relative uniformity (0 .. optimal)
            intensity_map: normalized intensity map, optimal is 1, <1 darker, >1 lighter
        """
        self._gray = cv2.cvtColor(self._image, cv2.COLOR_BGR2GRAY)
        h, w = self._gray.shape[:2]
        step_h = h // grid
        step_w = w // grid

        intensity_map = np.zeros((grid, grid), dtype=np.float32)
        y1 = 0
        for i in range(grid):
            x1 = 0
            for j in range(grid):
                roi = self._gray[y1:y1+step_h, x1:x1+step_w]
                intensity_map[i, j] = roi.mean()
                x1 += step_w
            y1 += step_h
        global_mean = intensity_map.mean()
        normalized_map = intensity_map / global_mean if global_mean > 0 else intensity_map
        uniformity = np.max(np.abs(normalized_map - 1.0))
        normalized_map= np.around(normalized_map, decimals=2)
        return uniformity, normalized_map

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
        putText(f"Color mode: {result.get('color_mode', None)} ({result.get('color_uniformity', None)}), Negative: {result.get('negative', None)}")
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

