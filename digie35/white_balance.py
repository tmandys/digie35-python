"""Bounded, measured LED white balance; preview sampling stays in the browser."""
import copy
import math
import uuid

from .color_profiles import BacklightCalibration


class WhiteBalance(BacklightCalibration):
    CHANNELS = ("red", "green", "blue")
    MAX_STEPS = 16

    def begin(self, owner, profile_id, camera_id, enable_gains=None):
        if self.session:
            raise ValueError("White balance is already running")
        if not camera_id:
            raise ValueError("Select a camera before white balance")
        state = self.digitizer.get_state()
        if state.get("movement", 0):
            raise ValueError("Stop film movement before white balance")
        light = state["backlight"]
        mode = light.get("color", "")
        caps = self.digitizer.get_capabilities()
        allowed = {"red+green+blue", "white+red+green+blue", "amber+white+red+green+blue"}
        if mode not in allowed or not (caps.get("rgb_backlight") or caps.get("rgbaw_backlight")):
            raise ValueError("Select an RGB, RGB+White or RGBAW mode with channel gains")
        if "white" in mode and not (caps.get("white_backlight") or caps.get("rgbaw_backlight")):
            raise ValueError("The light does not support this mode")
        if "amber" in mode and not caps.get("rgbaw_backlight"):
            raise ValueError("The light does not support RGBAW")
        gains = dict(light.get("gain", {}))
        if enable_gains is not None and not isinstance(enable_gains, dict):
            raise ValueError("Invalid RGB starting gains")
        for c in self.CHANNELS:
            if gains.get(c, 0) == 0:
                gains[c] = (enable_gains or {}).get(c, 1)
        if any(type(gains.get(c)) not in (int, float) or not math.isfinite(gains[c])
               or not 0.1 <= gains[c] <= 10 for c in self.CHANNELS):
            raise ValueError("RGB starting gains must be between 0.1 and 10")
        profile = self.profiles.get(profile_id)["profile"]
        if not set(mode.split("+")) <= set(profile["channels"]):
            raise ValueError("The selected profile does not cover this light mode")
        identity = self.light_identity(mode)
        keys = ("adapter_class", "adapter_id", "board_id", "version", "serial_number")
        if any(profile.get("light", {}).get(k) != identity.get(k) for k in keys):
            raise ValueError("Select a calibration profile for the connected light")
        camera = profile.get("camera", {})
        model = camera.get("id", "").split("|", 1)[1] if "|" in camera.get("id", "") else camera.get("model")
        if model and "|" in camera_id and model != camera_id.split("|", 1)[1]:
            raise ValueError("The calibration profile was measured with a different camera")
        original = {k: copy.deepcopy(light[k]) for k in ("color", "exposure", "gain", "temp") if k in light}
        # Adjust every enabled channel in this mode, including both white outputs.
        channels = [c for c in mode.split("+") if gains.get(c, 0) > 0]
        matrix = profile["matrix"]
        response = [[row[profile["channels"].index(c)] for c in channels] for row in matrix]
        self.solve([[row[profile["channels"].index(c)] for c in self.CHANNELS] for row in matrix], [1, 1, 1])  # Reject a singular response before acquiring hardware.
        base = copy.deepcopy(original)
        base["gain"] = gains
        self.session = {"owner": owner, "token": uuid.uuid4().hex, "base": base,
                        "original": copy.deepcopy(original), "hardware": self._light(mode),
                        "light": identity, "profile": profile, "response": response,
                        "channels": channels, "steps": 0, "converged": False, "previous_error": None, "worse": 0}
        self._touch()
        try:
            if base != original:
                self.digitizer.set_backlight(**base)
        except Exception:
            self.end(owner, self.session["token"])
            raise
        return {"token": self.session["token"], "settings": copy.deepcopy(base)}

    @staticmethod
    def solve(matrix, target):
        a = [list(row) + [value] for row, value in zip(matrix, target)]
        scale = max(abs(v) for row in matrix for v in row)
        for col in range(3):
            pivot = max(range(col, 3), key=lambda r: abs(a[r][col]))
            if abs(a[pivot][col]) <= max(1e-9, scale * 1e-5):
                raise ValueError("RGB response cannot independently correct color; select a suitable profile")
            a[col], a[pivot] = a[pivot], a[col]
            divisor = a[col][col]
            a[col] = [v / divisor for v in a[col]]
            for r in range(3):
                if r != col:
                    factor = a[r][col]
                    a[r] = [v - factor * p for v, p in zip(a[r], a[col])]
        return [row[3] for row in a]

    def _check(self, owner, token):
        s = self.session
        if not s or s["owner"] is not owner or s["token"] != token:
            raise ValueError("White balance session expired or belongs to another client")
        if self._light(s["base"]["color"]) is not s["hardware"] or self.light_identity(s["base"]["color"]) != s["light"]:
            raise ValueError("The connected light changed during white balance")
        return s

    def step(self, owner, token, rgb):
        s = self._check(owner, token)
        if not isinstance(rgb, list) or len(rgb) != 3 or any(type(v) not in (int, float)
                or not math.isfinite(v) or not 5 <= v <= 245 for v in rgb):
            raise ValueError("The selected area is too dark or clipped; adjust exposure before WB")
        mean = sum(rgb) / 3
        error = (max(rgb) - min(rgb)) / mean
        s["converged"] = max(rgb) - min(rgb) <= max(2, mean * 0.02)
        self._touch()
        if s["converged"]:
            return {"done": True, "rgb": rgb, "imbalance": error, "settings": copy.deepcopy(s["base"])}
        if s["steps"] >= self.MAX_STEPS:
            raise ValueError("WB did not converge within 16 steps; check the selected area and calibration profile")
        if s["previous_error"] is not None and error > s["previous_error"] * 1.15:
            s["worse"] += 1
        else:
            s["worse"] = 0
        if s["worse"] >= 2:
            raise ValueError("WB is moving away from neutral; check fixed camera WB and calibration profile")
        settings = copy.deepcopy(s["base"])
        gains = settings["gain"]
        p = s["profile"]
        # Estimate film attenuation per camera channel from the current measured RGB.
        predicted = [sum(row[j] * gains.get(c, 0) for j, c in enumerate(p["channels"])) for row in p["matrix"]]
        baseline = p.get("baseline", {})
        reference = baseline.get("settings", {}).get("gain", {})
        if len(baseline.get("rgb", [])) == 3 and all(c in reference for c in p["channels"]):
            predicted = [baseline["rgb"][r] + sum(row[j] * (gains.get(c, 0) - reference[c])
                         for j, c in enumerate(p["channels"])) for r, row in enumerate(p["matrix"])]
        if any(v <= 1e-6 for v in predicted):
            raise ValueError("The profile cannot predict a usable RGB response")
        jacobian = [[v * rgb[r] / predicted[r] for v in row] for r, row in enumerate(s["response"])]
        channels = s["channels"]
        hardware = s["hardware"]
        bounds = []
        for c in channels:
            minimum, maximum = 10, 1000  # hundredths, matching the gain controls
            if hasattr(hardware, "get_backlight_pwm_status"):
                probe = copy.deepcopy(settings)
                def status(value):
                    probe["gain"][c] = value / 100
                    return hardware.get_backlight_pwm_status(**probe)[c]
                # PWM is monotonic in channel gain. Find the usable quantized
                # interval without issuing any hardware commands.
                lo, hi = minimum, maximum
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if status(mid)["clipped"]: hi = mid - 1
                    else: lo = mid
                maximum = lo
                lo, hi = minimum, maximum
                while lo < hi:
                    mid = (lo + hi) // 2
                    if status(mid)["actual"] > 0: hi = mid
                    else: lo = mid + 1
                minimum = lo
                if status(minimum)["clipped"] or status(minimum)["actual"] <= 0:
                    raise ValueError("WB has no usable PWM range; adjust LED exposure")
            # Faster reductions of white, but still measure after every step.
            reduction = 0.35 if c in ("white", "amber") else 0.20
            lower = max(minimum / 100, gains[c] * (1 - reduction))
            upper = min(maximum / 100, gains[c] * 1.15)
            # Recover from an already clipped starting gain as well.
            lower = min(lower, maximum / 100)
            upper = max(upper, minimum / 100)
            bounds.append((lower - gains[c], upper - gains[c]))

        # Minimize chromatic error, allowing the common brightness to change.
        # A weak brightness preference avoids needless dimming when there is
        # headroom. Bound-constrained coordinate descent redistributes correction
        # as soon as one output hits a limit, even with fewer than 3 free LEDs.
        averages = [sum(row[j] for row in jacobian) / 3 for j in range(len(channels))]
        matrix = [[row[j] - averages[j] for j in range(len(channels))] for row in jacobian]
        matrix.append([0.05 * v for v in averages])
        target = [0.6 * (mean - v) for v in rgb] + [0]
        regularizer = max(sum(v*v for row in matrix for v in row) * 1e-5, 1e-9)
        delta = [max(low, min(high, 0)) for low, high in bounds]
        residual = [sum(v*d for v,d in zip(row, delta)) - t for row,t in zip(matrix,target)]
        for _ in range(400):
            largest = 0
            for j, c in enumerate(channels):
                penalty = regularizer / gains[c] ** 2
                curvature = sum(row[j] ** 2 for row in matrix) + penalty
                gradient = sum(row[j] * r for row,r in zip(matrix,residual)) + penalty * delta[j]
                low, high = bounds[j]
                value = max(low, min(high, delta[j] - gradient / curvature))
                change = value - delta[j]
                delta[j] = value
                residual = [r + row[j] * change for row,r in zip(matrix,residual)]
                largest = max(largest, abs(change))
            if largest < 1e-6: break
        candidate = copy.deepcopy(settings)
        candidate["gain"].update({c: round(gains[c] + d, 2) for c,d in zip(channels,delta)})
        valid = candidate["gain"] != gains
        if valid and hasattr(hardware, "get_backlight_pwm_status"):
            pwm = hardware.get_backlight_pwm_status(**candidate)
            valid = all(not pwm[c]["clipped"] and pwm[c]["actual"] > 0 for c in channels)
        if valid:
            self.digitizer.set_backlight(**candidate)
            s["base"] = candidate
            s["steps"] += 1
            s["previous_error"] = error
            return {"done": False, "step": s["steps"], "rgb": rgb, "imbalance": error, "settings": copy.deepcopy(candidate)}
        raise ValueError("WB reached gain or PWM limits; adjust LED exposure before retrying")

    def end(self, owner, token, commit=False, keep_partial=False):
        s = self.session
        if not s or s["owner"] is not owner or s["token"] != token:
            raise ValueError("White balance session expired or belongs to another client")
        if commit and not s["converged"] and not keep_partial:
            raise ValueError("WB cannot be kept before neutral RGB is measured")
        try:
            self._check(owner, token)
            settings = s["base"] if commit else s["original"]
            self.digitizer.set_backlight(**settings)
            result = {"restored": not commit, "partial": bool(commit and not s["converged"]), "settings": copy.deepcopy(settings)}
            self.completed[owner] = {"token": token, "result": result}
            return result
        finally:
            self.session = None
            if self.timer:
                self.timer.cancel()
                self.timer = None
