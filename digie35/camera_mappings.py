"""Built-in and user-defined camera command mappings."""
import copy
import datetime
import json
import os
import uuid

import yaml

from digie35.camera_profiles import CameraProfiles
from digie35.camera_actions import CAMERA_ACTION_LABELS, PROFILE_ENTRY_ACTIONS, validate_camera_action_steps


class CameraMappings(CameraProfiles):
    CATEGORY = "camera_mappings"

    @classmethod
    def _validate(cls, mapping):
        if not isinstance(mapping, dict) or mapping.get("schema_version") != 1:
            raise ValueError("Unsupported camera mapping format")
        cls._name(mapping.get("name"))
        if not isinstance(mapping.get("actions", {}), dict):
            raise ValueError("Camera mapping actions must be an object")
        for action, definition in mapping.get("actions", {}).items():
            if not isinstance(definition, dict):
                raise ValueError("Camera action must be an object")
            if not isinstance(definition.get("steps", []), list):
                raise ValueError("Camera action steps must be a list")
        if len(json.dumps(mapping, ensure_ascii=False, allow_nan=False).encode("utf-8")) > cls._MAX_PROFILE_BYTES:
            raise ValueError("Camera mapping is too large")

    @staticmethod
    def _builtins():
        path = os.path.join(os.path.dirname(__file__), "camera_profiles", "action-mappings.yaml")
        with open(path, encoding="utf-8") as source:
            return yaml.safe_load(source)["mappings"]

    def list(self):
        result = super().list()
        result["builtins"] = copy.deepcopy(self._builtins())
        result["mappings"] = result.pop("profiles")
        result["action_labels"] = dict(CAMERA_ACTION_LABELS)
        result["profile_entry_actions"] = dict(PROFILE_ENTRY_ACTIONS)
        return result

    def get(self, identifier):
        """Return a built-in or user mapping selected by the browser."""
        for mapping in self._builtins():
            if mapping.get("id") == identifier:
                self._validate(mapping)
                self._validate_actions(mapping)
                return copy.deepcopy(mapping)
        mapping = super().get(identifier)
        self._validate_actions(mapping)
        return mapping

    @staticmethod
    def _validate_actions(mapping):
        # Keep structurally readable files in the editor even if somebody
        # removed/duplicated a mandatory step by editing JSON manually.
        for action, definition in mapping.get("actions", {}).items():
            validate_camera_action_steps(action, definition.get("steps", []))
            if "modes" in definition:
                modes = definition["modes"]
                if (not isinstance(modes, list) or not modes
                        or any(mode not in ("mf", "af") for mode in modes)
                        or len(set(modes)) != len(modes)):
                    raise ValueError("Action modes must be a nonempty list of mf and/or af")
                if action in PROFILE_ENTRY_ACTIONS.values() or action == "after_open":
                    raise ValueError("Mode restrictions are only supported for control actions")

    def save(self, mapping):
        self._validate(mapping)
        self._validate_actions(mapping)
        result = super().save(mapping)
        result["saved_mapping"] = result.pop("saved_profile")
        return result

    def delete(self, identifier):
        return super().delete(identifier)
