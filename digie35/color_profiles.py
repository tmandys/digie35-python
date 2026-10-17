"""Portable backlight response profiles and bounded calibration sessions."""
import asyncio
import copy
import datetime
import json
import logging
import math
from pathlib import Path
import re
from threading import RLock
import unicodedata
import uuid


class ColorProfiles:
    CATEGORY = "color_profiles"

    def __init__(self, storage, builtin_directory=None):
        self.storage = storage
        self.builtin_directory = Path(builtin_directory or Path(__file__).with_name(self.CATEGORY))
        self.lock = RLock()

    @staticmethod
    def name(value):
        if not isinstance(value, str):
            raise ValueError("Profile name must be text")
        value = unicodedata.normalize("NFC", value.strip())
        if not value or len(value) > 100 or any(ord(c) < 32 for c in value):
            raise ValueError("Use a profile name of 1–100 characters")
        return value

    @staticmethod
    def validate(profile):
        if not isinstance(profile, dict) or profile.get("schema_version") != 1:
            raise ValueError("Unsupported color profile format")
        if profile.get("units") != "preview_rgb_per_channel_gain":
            raise ValueError("Unsupported response matrix units")
        ColorProfiles.name(profile.get("name"))
        channels = profile.get("channels")
        if not isinstance(channels, list) or not channels or len(set(channels)) != len(channels):
            raise ValueError("Invalid profile channels")
        if not set(channels) <= {"red", "green", "blue", "white", "amber", "ir", "preview"}:
            raise ValueError("Unsupported profile channels")
        matrix = profile.get("matrix")
        if not isinstance(matrix, list) or len(matrix) != 3:
            raise ValueError("Expected a 3 x channel-count response matrix")
        for row in matrix:
            if not isinstance(row, list) or len(row) != len(channels):
                raise ValueError("Invalid response matrix dimensions")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in row):
                raise ValueError("Response matrix must contain finite numbers")
        if len(json.dumps(profile, allow_nan=False).encode("utf-8")) > 128 * 1024:
            raise ValueError("Profile is too large")

    def records(self):
        result = []
        sources = [("builtin", self.builtin_directory.glob("*.json")),
                   ("user", (self.storage._path(self.CATEGORY, name) for name in self.storage.list(self.CATEGORY)))]
        for source, paths in sources:
            for path in paths:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", path.stem):
                    continue
                try:
                    profile = json.loads(path.read_text(encoding="utf-8"))
                    self.validate(profile)
                    result.append({"id": source + ":" + path.stem, "source": source, "profile": profile})
                except (OSError, ValueError, TypeError) as error:
                    logging.warning("Ignoring invalid color profile %s: %s", path, error)
        return sorted(result, key=lambda item: (item["profile"]["name"].casefold(), item["id"]))

    def list(self):
        with self.lock:
            return {"profiles": [{"id": r["id"], "source": r["source"], "name": r["profile"]["name"],
                                  "light": r["profile"].get("light"),
                                  "channels": r["profile"]["channels"]} for r in self.records()]}

    def check_name(self, name):
        name = self.name(name)
        with self.lock:
            if any(self.name(r["profile"]["name"]).casefold() == name.casefold() for r in self.records()):
                raise ValueError("A profile with this name already exists")
        return {"name": name}

    def get(self, id):
        with self.lock:
            for record in self.records():
                if record["id"] == id:
                    return record
        raise ValueError("Profile not found")

    def save(self, profile):
        self.validate(profile)
        with self.lock:
            profile = copy.deepcopy(profile)
            profile["name"] = self.check_name(profile["name"])["name"]
            profile["created_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            identifier = uuid.uuid4().hex
            self.storage.save(self.CATEGORY, identifier, profile)
            return {"id": "user:" + identifier, "name": profile["name"]}

    def delete(self, id):
        with self.lock:
            record = self.get(id)
            if record["source"] != "user":
                raise ValueError("Built-in profiles cannot be deleted")
            self.storage._path(self.CATEGORY, id.split(":", 1)[1]).unlink()
            return {"id": id}


class BacklightCalibration:
    """Only one owner may change light during calibration; inactivity restores it."""
    TIMEOUT = 120

    def __init__(self, digitizer, profiles, camera=None):
        self.digitizer = digitizer
        self.profiles = profiles
        self.camera = camera
        self.session = None
        self.timer = None
        self.completed = {}

    def _light(self, mode):
        adapter = self.digitizer.get_adapter(getattr(self.digitizer, "LIGHT_NAME", "light"))
        if adapter is not None and mode == "preview" and not adapter.get_capability("preview_backlight"):
            adapter = None  # Preview may be driven by the main board, not the light adapter.
        return adapter or self.digitizer

    def light_identity(self, mode):
        device = self._light(mode)
        memory = device.get_memory() if hasattr(device, "get_memory") else getattr(device, "_xboard_memory", None)
        header = memory.read_header() if memory is not None else {}
        serial = header.get("serial_number")
        return {"name": header.get("human_name") or type(device).__name__,
                "adapter_class": type(device).__name__, "adapter_id": header.get("adapter_id", getattr(device, "ID", None)),
                "board_id": header.get("board_id"), "version": header.get("version"),
                # EEPROM numbers can exceed JavaScript's safe integer range.
                "serial_number": str(serial) if serial not in (None, 0, "", "0", 2**64 - 1) else None}

    def calibration_mode(self):
        caps = self.digitizer.get_capabilities()
        if caps.get("rgbaw_backlight"):
            return "amber+white+red+green+blue"
        if caps.get("rgb_backlight"):
            return ("white+" if caps.get("white_backlight") else "") + "red+green+blue"
        if caps.get("white_backlight"):
            return "white"
        raise ValueError("The connected light has no supported visible calibration channels")

    def info(self):
        mode = self.calibration_mode()
        labels = {c: c.capitalize() for c in mode.split("+")}
        if self.digitizer.get_capabilities().get("temperature_backlight") and "amber" in labels:
            labels.update(white="White 5000 K", amber="White 3000 K")
        return {"mode": mode, "channels": mode.split("+"), "channel_labels": labels,
                "light": self.light_identity(mode)}

    def _touch(self):
        if self.timer:
            self.timer.cancel()
        self.timer = asyncio.get_running_loop().call_later(self.TIMEOUT, self._expire)

    def _expire(self):
        try:
            self.end(self.session["owner"], self.session["token"])
        except Exception:
            logging.exception("Cannot restore backlight after calibration timeout")

    def begin(self, owner, name, isolated=False, camera_profile=None, camera_id=None):
        if self.session:
            raise ValueError("A backlight calibration is already running")
        name = self.profiles.check_name(name)["name"]
        if not camera_profile or not camera_id:
            raise ValueError("Select a camera and a calibration camera profile before calibration")
        if self.camera is None:
            raise ValueError("Camera calibration profiles are not available")
        camera_transaction = self.camera.begin_camera_profile_transaction(camera_profile, camera_id, "calibration")
        try:
            return self._begin(owner, name, isolated, camera_transaction)
        except Exception:
            restore = self.camera.restore_camera_profile_transaction(camera_transaction)
            if not restore["restored"]:
                logging.getLogger().warning(restore["warning"])
            raise

    def _begin(self, owner, name, isolated, camera_transaction):
        state = self.digitizer.get_state()
        if state.get("movement", 0):
            raise ValueError("Stop film movement before calibration")
        light = copy.deepcopy(state["backlight"])
        color = self.calibration_mode()
        original = {key: light[key] for key in ("color", "exposure", "gain", "temp") if key in light}
        if not original.get("color"):
            original = {"color": None}
        gains = light.get("gain", {}) if not isolated and color == light.get("color") else {}
        channels = color.split("+")
        levels = {c: gains[c] if gains.get(c, 0) > 0 else 1 for c in channels}
        if any(not math.isfinite(v) or v < 0 or v > 10 for v in levels.values()):
            raise ValueError("Invalid starting channel levels")
        base = {"color": color, "exposure": light.get("exposure") if light.get("exposure") is not None else 0,
                "gain": levels, "temp": None if isolated else light.get("temp")}
        identity = self.light_identity(color)
        hardware = self._light(color)
        if any(value * 1.2 > 10 for value in levels.values()):
            raise ValueError("Lower channel gains below 8.33 to leave calibration headroom")
        exposure_options = []
        # Use the UI's EV range and verify both probe extremes before any LED writes.
        for exposure in (step / 2 for step in range(-5, 6)):
            if hasattr(hardware, "get_backlight_pwm_status"):
                probe = dict(base, exposure=exposure)
                low = hardware.get_backlight_pwm_status(**dict(probe, gain={c: v * 0.8 for c, v in levels.items()}))
                high = hardware.get_backlight_pwm_status(**dict(probe, gain={c: v * 1.2 for c, v in levels.items()}))
                if any(high[c]["at_limit"] or high[c]["clipped"] or low[c]["actual"] <= 0
                       or high[c]["actual"] <= low[c]["actual"] for c in channels):
                    continue
            exposure_options.append(exposure)
        if not exposure_options:
            raise ValueError("No LED EV setting leaves PWM headroom for all channels. Adjust channel gains.")
        base["exposure"] = min(exposure_options, key=lambda ev: abs(ev - base["exposure"]))
        self.completed.pop(owner, None)
        self.session = {"owner": owner, "token": uuid.uuid4().hex, "name": name, "base": base,
                        "original": original, "hardware": self._light(color), "light": identity,
                        "levels": levels, "channels": channels, "exposure_options": exposure_options,
                        "setup": {"board": type(self.digitizer).__name__},
                        "camera_transaction": camera_transaction}
        if isolated:
            self.session.update(method="whole_lightbox", channel_labels=self.info()["channel_labels"],
                                isolated_levels=dict(levels), isolated_settings={})
        self._touch()
        return {k: copy.deepcopy(v) for k, v in self.session.items() if k not in ("owner", "hardware", "original")}

    def _check(self, owner, token):
        if not self.session or self.session["owner"] is not owner or self.session["token"] != token:
            raise ValueError("Calibration session expired or belongs to another client")
        if self._light(self.session["base"]["color"]) is not self.session["hardware"]:
            raise ValueError("The connected light changed during calibration")
        if self.calibration_mode() != self.session["base"]["color"]:
            raise ValueError("Light capabilities changed during calibration")
        return self.session

    def step(self, owner, token, channel=None, factor=1, exposure=None, phase="mixture", level=None):
        session = self._check(owner, token)
        if phase not in ("mixture", "isolated") or (phase == "isolated" and (session.get("method") != "whole_lightbox" or channel is None)):
            raise ValueError("Unsupported calibration phase")
        if level is not None and (phase != "isolated" or factor != 1 or type(level) not in (int, float)
                                  or not math.isfinite(level) or not 0.1 <= level <= 8.33):
            raise ValueError("Unsupported isolated channel level")
        if channel is not None and channel not in session["channels"]:
            raise ValueError("Channel is not part of this calibration")
        if type(factor) not in (int, float) or factor not in (0.8, 1, 1.2):
            raise ValueError("Unsupported calibration step")
        if exposure is not None and (type(exposure) not in (int, float)
                                    or exposure not in session["exposure_options"] or channel is not None or factor != 1):
            raise ValueError("Unsupported calibration EV or insufficient PWM headroom")
        settings = copy.deepcopy(session["base"])
        if exposure is not None:
            settings["exposure"] = exposure
        settings["gain"] = dict(session["levels"])
        if phase == "isolated":
            settings["gain"] = {c: 0 for c in session["channels"]}
        if channel:
            channel_level = (level if level is not None else session["isolated_levels"][channel]) if phase == "isolated" else session["levels"][channel]
            value = channel_level * factor
            maximum = 1 if settings.get("exposure") is None else 10
            if value > maximum:
                raise ValueError("Lower the starting channel level to leave calibration headroom")
            settings["gain"][channel] = value
        if phase == "isolated":
            hardware = session["hardware"]
            if hasattr(hardware, "get_backlight_pwm_status"):
                for probe_factor in (0.8, 1.2):
                    probe = copy.deepcopy(settings)
                    probe["gain"][channel] = channel_level * probe_factor
                    pwm = hardware.get_backlight_pwm_status(**probe)[channel]
                    if pwm["clipped"] or pwm["at_limit"] or pwm["actual"] <= 0:
                        self._touch()
                        return {"limited": True, "reason": "PWM headroom", "settings": settings}
        self.digitizer.set_backlight(**settings)
        if phase == "isolated":
            session["isolated_levels"][channel] = channel_level
            session["isolated_settings"][channel] = dict(copy.deepcopy(settings), gain={c: channel_level if c == channel else 0 for c in session["channels"]})
        if exposure is not None:
            session["base"]["exposure"] = exposure
        self._touch()
        return {"settings": settings, "level": settings["gain"].get(channel) if channel else None}

    def end(self, owner, token):
        session = self.session
        if not session or session["owner"] is not owner or session["token"] != token:
            raise ValueError("Calibration session expired or belongs to another client")
        camera_restore = {"restored": True, "restored_parameters": [], "unchanged_parameters": [], "warning": None}
        try:
            self._check(owner, token)
            self.digitizer.set_backlight(**session["original"])
            self.completed[owner] = {k: copy.deepcopy(session[k]) for k in ("token", "name", "base", "channels", "light", "setup")}
            for key in ("method", "channel_labels", "isolated_settings"):
                if key in session:
                    self.completed[owner][key] = copy.deepcopy(session[key])
        finally:
            if session.get("camera_transaction"):
                camera_restore = self.camera.restore_camera_profile_transaction(session["camera_transaction"])
                if not camera_restore["restored"]:
                    logging.getLogger().warning(camera_restore["warning"])
            self.session = None
            if self.timer:
                self.timer.cancel()
                self.timer = None
        return {"restored": True, "camera_restore": camera_restore}

    def disconnect(self, owner):
        if self.session and self.session["owner"] is owner:
            self.end(owner, self.session["token"])
        self.completed.pop(owner, None)

    def save_profile(self, owner, token, profile):
        session = self.completed.get(owner)
        if not session or session["token"] != token:
            raise ValueError("No completed calibration for this client")
        if self.light_identity(session["base"]["color"]) != session["light"]:
            raise ValueError("The connected light changed; repeat calibration")
        profile = copy.deepcopy(profile)
        profile.update({"name": session["name"], "light": session["light"], "setup": session["setup"],
                        "channels": session["channels"], "mode": session["base"]["color"]})
        profile["baseline"]["settings"] = session["base"]
        if session.get("method") == "whole_lightbox":
            profile.update(scope="lightbox", method=session["method"], channel_labels=session["channel_labels"])
            for channel in session["channels"]:
                sample = profile.get("isolated_samples", {}).get(channel)
                if not sample or channel not in session["isolated_settings"]:
                    raise ValueError("Missing isolated channel measurements")
                sample["settings"] = session["isolated_settings"][channel]
        result = self.profiles.save(profile)
        self.completed.pop(owner, None)
        return result
