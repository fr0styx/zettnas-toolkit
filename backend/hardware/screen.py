import glob
import json
import os
import time

from backend.config import SCREEN_STATE_FILE


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


def set_screen_brightness(pct):
    pct = max(0, min(100, int(pct)))
    backlight_dir = "/sys/class/backlight/intel_backlight"
    if not os.path.exists(backlight_dir):
        for bl in sorted(glob.glob("/sys/class/backlight/*")):
            if os.path.exists(os.path.join(bl, "brightness")):
                backlight_dir = bl
                break
    if not os.path.exists(backlight_dir):
        return False
    try:
        max_val = 192000
        max_path = os.path.join(backlight_dir, "max_brightness")
        if os.path.exists(max_path):
            max_val = int(open(max_path).read().strip() or 192000)
        target = int((pct / 100.0) * max_val)
        with open(os.path.join(backlight_dir, "brightness"), "w") as f:
            f.write(f"{target}\n")
        return True
    except Exception:
        return False
