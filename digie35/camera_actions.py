"""Shared action names for camera mappings and profile mode transitions."""
import math

CAMERA_ACTION_LABELS = {
    "after_open": "After camera open",
    "enter_mf": "Enter MF profile",
    "enter_af": "Enter AF profile",
    "meter_exposure": "Meter exposure",
    "autofocus": "Autofocus",
    "focus_near_1": "Focus nearer — small step",
    "focus_near_2": "Focus nearer — medium step",
    "focus_near_3": "Focus nearer — large step",
    "focus_far_1": "Focus farther — small step",
    "focus_far_2": "Focus farther — medium step",
    "focus_far_3": "Focus farther — large step",
}

# Focus uses the MF camera sequence, but keeps its own parameter values.
PROFILE_ENTRY_ACTIONS = {"mf": "enter_mf", "focus": "enter_mf", "af": "enter_af"}


def validate_camera_action_steps(action, steps):
    """Only flat parameter, delay and profile steps are executable."""
    if not isinstance(steps, list):
        raise ValueError("Camera action steps must be a list")
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Invalid camera-action step")
        if set(step) == {"apply_profile"} and step["apply_profile"] is True:
            continue
        if set(step) == {"delay_ms"}:
            delay = step["delay_ms"]
            if isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay):
                continue
        if set(step) == {"id", "value"} and isinstance(step["id"], str) and step["id"] and step["value"] is not None:
            continue
        raise ValueError("Use a parameter, Wait, or Apply profile parameters step; nested actions are not supported")
    count = sum(step.get("apply_profile") is True for step in steps)
    if action in PROFILE_ENTRY_ACTIONS.values():
        if count != 1:
            raise ValueError(f"{CAMERA_ACTION_LABELS.get(action, action)} requires exactly one Apply profile parameters step (found {count})")
    elif count:
        raise ValueError("Apply profile parameters is only supported in entry actions")
