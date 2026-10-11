"""Named LED gain presets; exposure is deliberately not part of a preset."""
import copy
import datetime
import logging
import math
import re
import uuid
from threading import RLock

from digie35.color_profiles import ColorProfiles


class LedPresets:
    CATEGORY = "led_presets"
    MODES = ("red+green+blue", "white+red+green+blue", "amber+white+red+green+blue")

    def __init__(self, storage, calibration):
        self.storage, self.calibration = storage, calibration
        self.lock = RLock()

    @staticmethod
    def identity(light):
        return {k: light.get(k) for k in ("adapter_class", "adapter_id", "board_id", "version", "serial_number")}

    def modes(self):
        caps = self.calibration.digitizer.get_capabilities()
        return [m for m, supported in zip(self.MODES, (
            caps.get("rgb_backlight"), caps.get("rgb_backlight") and caps.get("white_backlight"),
            caps.get("rgbaw_backlight"))) if supported]

    @classmethod
    def settings(cls, settings):
        if not isinstance(settings, dict) or settings.get("mode") not in cls.MODES:
            raise ValueError("Presets require RGB, RGB+White or RGBAW mode")
        channels = settings["mode"].split("+")
        gains, enabled = settings.get("gains"), settings.get("enabled")
        if not isinstance(gains, dict) or not isinstance(enabled, dict) or set(gains) != set(channels) or set(enabled) != set(channels):
            raise ValueError("Preset channels do not match its light mode")
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0.1 <= v <= 10 for v in gains.values()):
            raise ValueError("Preset gains must be between 0.1 and 10")
        if any(type(v) is not bool for v in enabled.values()):
            raise ValueError("Invalid channel switches")
        return {"mode": settings["mode"], "gains": dict(gains), "enabled": dict(enabled)}

    def current_light(self):
        modes = self.modes()
        return self.calibration.light_identity(modes[0] if modes else "white")

    def read(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
            raise ValueError("Invalid LED preset ID")
        data = self.storage.load(self.CATEGORY, identifier)
        if data.get("schema_version") != 1 or not isinstance(data.get("light"), dict):
            raise ValueError("Invalid LED preset format")
        ColorProfiles.name(data.get("name"))
        self.settings(data)
        return data

    def listing(self):
        with self.lock:
            light, modes = self.current_light(), self.modes()
            presets = []
            for identifier in self.storage.list(self.CATEGORY):
                try:
                    data = self.read(identifier)
                    if data["mode"] in modes and self.identity(data["light"]) == self.identity(light):
                        presets.append(dict(data, id=identifier))
                except (OSError, ValueError, TypeError, AttributeError) as error:
                    logging.warning("Ignoring invalid LED preset %s: %s", identifier, error)
            return {"light": light, "modes": modes, "presets": sorted(presets, key=lambda p: (p["name"].casefold(), p["id"]))}

    def save(self, name, settings, identifier=None, expected_light=None):
        with self.lock:
            current = self.listing()
            light = current["light"]
            if not isinstance(expected_light, dict) or self.identity(expected_light) != self.identity(light):
                raise ValueError("Connected light changed; refresh presets")
            data = self.settings(settings)
            if data["mode"] not in current["modes"]:
                raise ValueError("Preset mode is unavailable on this light")
            name = ColorProfiles.name(name)
            existing = next((p for p in current["presets"] if p["id"] == identifier), None)
            if identifier is not None and (existing is None or existing["mode"] != data["mode"]):
                raise ValueError("Preset does not belong to this light and mode")
            if any(p["id"] != identifier and p["mode"] == data["mode"] and p["name"].casefold() == name.casefold() for p in current["presets"]):
                raise ValueError("A preset with this name already exists for this mode")
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            data.update(schema_version=1, name=name, light=copy.deepcopy(light),
                        created_at=existing["created_at"] if existing else now, updated_at=now)
            identifier = identifier or uuid.uuid4().hex
            self.storage.save(self.CATEGORY, identifier, data)
            return dict(data, id=identifier)

    def delete(self, identifier):
        with self.lock:
            if not any(p["id"] == identifier for p in self.listing()["presets"]):
                raise ValueError("Preset is unavailable for this light")
            self.storage._path(self.CATEGORY, identifier).unlink()
            return {"id": identifier}
