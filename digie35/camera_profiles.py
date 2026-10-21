"""Disk-backed user camera profiles using shared local JSON storage."""
import copy
import datetime
import json
import re
from threading import RLock
import unicodedata
import uuid

from digie35.storage import LocalStorage


class CameraProfiles:
    CATEGORY = "camera_profiles"
    _IDENTIFIER = re.compile(r"[a-f0-9]{32}")
    _MAX_PROFILE_BYTES = 256 * 1024

    def __init__(self, storage):
        if not isinstance(storage, LocalStorage):
            storage = LocalStorage(storage)
        self.storage = storage
        self.lock = RLock()

    @classmethod
    def _identifier(cls, value):
        if not isinstance(value, str) or not cls._IDENTIFIER.fullmatch(value):
            raise ValueError("Camera profile ID must be a UUID")
        return value

    @staticmethod
    def _name(value):
        if not isinstance(value, str):
            raise ValueError("Camera profile name must be text")
        value = unicodedata.normalize("NFC", value.strip())
        if not value or len(value) > 100 or any(ord(char) < 32 for char in value):
            raise ValueError("Use a camera profile name of 1–100 characters")
        return value

    @classmethod
    def _validate(cls, profile):
        if not isinstance(profile, dict) or profile.get("schema_version") != 1:
            raise ValueError("Unsupported camera profile format")
        cls._name(profile.get("name"))
        if not isinstance(profile.get("parameters", {}), dict):
            raise ValueError("Camera profile parameters must be an object")
        if len(json.dumps(profile, ensure_ascii=False, allow_nan=False).encode("utf-8")) > cls._MAX_PROFILE_BYTES:
            raise ValueError("Camera profile is too large")

    def _read(self, identifier):
        identifier = self._identifier(identifier)
        try:
            profile = self.storage.load(self.CATEGORY, identifier)
        except (OSError, ValueError) as error:
            raise ValueError("Camera profile not found") from error
        self._validate(profile)
        if profile.get("id") != identifier:
            raise ValueError("Camera profile ID does not match its record")
        return profile

    def list(self):
        with self.lock:
            profiles = []
            for identifier in self.storage.list(self.CATEGORY):
                try:
                    profiles.append(self._read(identifier))
                except ValueError:
                    continue
            profiles.sort(key=lambda profile: (profile["name"].casefold(), profile["id"]))
            return {"profiles": copy.deepcopy(profiles)}

    def get(self, identifier):
        """Return one validated profile by its opaque server-side ID."""
        with self.lock:
            return copy.deepcopy(self._read(identifier))

    def save(self, profile):
        self._validate(profile)
        with self.lock:
            profile = copy.deepcopy(profile)
            profile.pop("mode_actions", None)  # Superseded by mapping entry actions.
            identifier = profile.get("id")
            if identifier is None:
                identifier = uuid.uuid4().hex
                created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            else:
                identifier = self._identifier(identifier)
                created_at = self._read(identifier).get("created_at")
            profile["id"] = identifier
            profile["name"] = self._name(profile["name"])
            profile["created_at"] = created_at
            profile["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.storage.save(self.CATEGORY, identifier, profile)
            result = self.list()
            result["saved_profile"] = copy.deepcopy(profile)
            return result

    def delete(self, identifier):
        with self.lock:
            try:
                self.storage.delete(self.CATEGORY, self._identifier(identifier))
            except (OSError, ValueError) as error:
                raise ValueError("Camera profile not found") from error
            return self.list()
