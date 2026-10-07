import glob
import json
import os
import time

from backend.config import SCREEN_STATE_FILE
from backend.fsutil import atomic_write_json


def is_in_time_window(start_str, end_str, now_minutes=None):
    """True if the current local time (or `now_minutes` since midnight) falls
    inside [start, end). Windows may wrap past midnight (e.g. 23:00-07:00)."""
    try:
        if now_minutes is None:
            now = time.localtime()
            curr_min = now.tm_hour * 60 + now.tm_min
        else:
            curr_min = int(now_minutes)
        s_h, s_m = map(int, start_str.split(":"))
        e_h, e_m = map(int, end_str.split(":"))
        s_val = s_h * 60 + s_m
        e_val = e_h * 60 + e_m
        if s_val <= e_val:
            return s_val <= curr_min < e_val
        else:
            return curr_min >= s_val or curr_min < e_val
    except Exception:
        return False


def get_screen_state():
    state = {
        "brightness": 100,
        "night_mode": False,
        "night_start": "23:00",
        "night_end": "07:00",
        "night_brightness": 10,
    }
    if os.path.exists(SCREEN_STATE_FILE):
        try:
            with open(SCREEN_STATE_FILE) as f:
                state.update(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return state


def discover_backlight_dir():
    candidates = [
        "/sys/class/backlight/intel_backlight",
        "/host/sys/class/backlight/intel_backlight",
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, "brightness")):
            return c
    for base in ["/sys/class/backlight", "/host/sys/class/backlight"]:
        if os.path.isdir(base):
            for bl in sorted(glob.glob(f"{base}/*")):
                if os.path.exists(os.path.join(bl, "brightness")):
                    return bl
    return None


def get_effective_brightness():
    cfg = get_screen_state()
    brightness = cfg.get("brightness", 100)
    if cfg.get("night_mode") and is_in_time_window(cfg.get("night_start", "23:00"), cfg.get("night_end", "07:00")):
        return int(cfg.get("night_brightness", 10))
    return int(brightness)


def set_screen_brightness(pct):
    pct = max(0, min(100, int(pct)))
    backlight_dir = discover_backlight_dir()
    if not backlight_dir:
        return False
    try:
        max_val = 192000
        max_path = os.path.join(backlight_dir, "max_brightness")
        if os.path.exists(max_path):
            with open(max_path) as mf:
                max_val = int(mf.read().strip() or 192000)
        target = int((pct / 100.0) * max_val)
        with open(os.path.join(backlight_dir, "brightness"), "w") as f:
            f.write(f"{target}\n")
        return True
    except Exception:
        return False


def save_screen_state(updates: dict):
    state = get_screen_state()
    state.update(updates)
    atomic_write_json(SCREEN_STATE_FILE, state)
    eff_bri = get_effective_brightness()
    set_screen_brightness(eff_bri)
    return state
