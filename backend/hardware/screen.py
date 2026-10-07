import glob
import json
import os
import time

from backend.config import HOST_SYS, SCREEN_STATE_FILE, logger
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


_cached_screen_state: dict | None = None
_cached_screen_key: tuple[str, int, int] = ("", 0, 0)


def get_screen_state():
    global _cached_screen_state, _cached_screen_key
    try:
        if os.path.exists(SCREEN_STATE_FILE):
            st = os.stat(SCREEN_STATE_FILE)
            key = (str(SCREEN_STATE_FILE), st.st_mtime_ns, st.st_size)
            if _cached_screen_state is not None and key == _cached_screen_key:
                return dict(_cached_screen_state)
            _cached_screen_key = key
    except OSError:
        if _cached_screen_state is not None:
            return dict(_cached_screen_state)

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
    _cached_screen_state = state
    return dict(state)


def discover_backlight_dir():
    """
    Locates the sysfs backlight directory.
    Prioritizes writable paths under HOST_SYS (e.g. /host/sys/class/backlight mounted rw in Docker),
    falling back to container-local /sys/class/backlight.
    """
    bases = []
    if HOST_SYS and os.path.isdir(os.path.join(HOST_SYS, "class/backlight")):
        bases.append(os.path.join(HOST_SYS, "class/backlight"))
    if "/host/sys/class/backlight" not in bases and os.path.isdir("/host/sys/class/backlight"):
        bases.append("/host/sys/class/backlight")
    if "/sys/class/backlight" not in bases and os.path.isdir("/sys/class/backlight"):
        bases.append("/sys/class/backlight")

    priority_names = ["intel_backlight"]

    # 1. Search for writable brightness sysfs entries (avoids read-only container /sys)
    for base in bases:
        for name in priority_names:
            c = os.path.join(base, name)
            b = os.path.join(c, "brightness")
            if os.path.exists(b) and os.access(b, os.W_OK):
                return c
        for c in sorted(glob.glob(os.path.join(base, "*"))):
            b = os.path.join(c, "brightness")
            if os.path.exists(b) and os.access(b, os.W_OK):
                return c

    # 2. Fallback to any existing brightness entry (for mock environments / unit tests)
    for base in bases:
        for name in priority_names:
            c = os.path.join(base, name)
            b = os.path.join(c, "brightness")
            if os.path.exists(b):
                return c
        for c in sorted(glob.glob(os.path.join(base, "*"))):
            b = os.path.join(c, "brightness")
            if os.path.exists(b):
                return c

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
    except Exception as e:
        logger.warning(f"[SCREEN] Failed to set brightness in {backlight_dir}: {e}")
        # Secondary fallback: if path was under read-only /sys, attempt writing under /host/sys
        if "/sys/" in backlight_dir and not backlight_dir.startswith("/host/sys"):
            fallback_dir = backlight_dir.replace("/sys/", "/host/sys/", 1)
            b_file = os.path.join(fallback_dir, "brightness")
            if os.path.exists(b_file):
                try:
                    with open(b_file, "w") as f:
                        f.write(f"{target}\n")
                    return True
                except Exception as ex:
                    logger.warning(f"[SCREEN] Fallback write to {fallback_dir} also failed: {ex}")
        return False


def save_screen_state(updates: dict):
    global _cached_screen_state, _cached_screen_key
    state = get_screen_state()
    state.update(updates)
    atomic_write_json(SCREEN_STATE_FILE, state)
    try:
        st = os.stat(SCREEN_STATE_FILE)
        _cached_screen_key = (str(SCREEN_STATE_FILE), st.st_mtime_ns, st.st_size)
    except OSError:
        pass
    _cached_screen_state = state
    eff_bri = get_effective_brightness()
    set_screen_brightness(eff_bri)
    return dict(state)
