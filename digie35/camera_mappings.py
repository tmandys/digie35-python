"""Built-in and user-defined camera command mappings."""
import copy
import datetime
import json
import os
import uuid

import yaml

from digie35.camera_profiles import CameraProfiles


class CameraMappings(CameraProfiles):
    CATEGORY = "camera_mappings"

    @classmethod
    def _validate(cls, mapping):
        if not isinstance(mapping, dict) or mapping.get("schema_version") != 1:
            raise ValueError("Unsupported camera mapping format")
        cls._name(mapping.get("name"))
        if not isinstance(mapping.get("actions", {}), dict):
            raise ValueError("Camera mapping actions must be an object")
        if len(json.dumps(mapping, ensure_ascii=False, allow_nan=False).encode("utf-8")) > cls._MAX_PROFILE_BYTES:
            raise ValueError("Camera mapping is too large")

    @staticmethod
    def _builtins():
        path = os.path.join(os.path.dirname(__file__), "camera_profiles", "builtin-mappings.yaml")
        with open(path, encoding="utf-8") as source:
            return yaml.safe_load(source)["mappings"]

    def list(self):
        result = super().list()
        result["builtins"] = copy.deepcopy(self._builtins())
        result["mappings"] = result.pop("profiles")
        return result

    def get(self, identifier):
        """Return a built-in or user mapping selected by the browser."""
        for mapping in self._builtins():
            if mapping.get("id") == identifier:
                self._validate(mapping)
                return copy.deepcopy(mapping)
        return super().get(identifier)

    def save(self, mapping):
        result = super().save(mapping)
        result["saved_mapping"] = result.pop("saved_profile")
        return result

    def delete(self, identifier):
        return super().delete(identifier)
