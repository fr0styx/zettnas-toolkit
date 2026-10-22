import glob
import json
import os
import time

from backend.config import HOST_DEV, HOST_SYS, SCREEN_STATE_FILE, logger
from backend.fsutil import atomic_write_json


def find_fb_device(writable_only: bool = True) -> str | None:
    """
    Discovers an accessible framebuffer character device.
    Prioritizes FRAMEBUFFER env, /dev/fb0, HOST_DEV/fb0, and /host/dev/fb0.
    If writable_only=True, verifies that the device can be opened for r+b (verifying cgroup permissions).
    Returns device path or None.
    """
    candidates = []
    if "FRAMEBUFFER" in os.environ:
        candidates.append(os.environ["FRAMEBUFFER"])
    candidates.extend(
        [
            "/dev/fb0",
            os.path.join(HOST_DEV, "fb0") if HOST_DEV else "/host/dev/fb0",
            "/host/dev/fb0",
        ]
    )

    seen = set()
    for cand in candidates:
        if not cand or cand in seen:
            continue
        seen.add(cand)
        if os.path.exists(cand) and not os.path.isdir(cand):
            if writable_only:
                try:
                    with open(cand, "r+b"):
                        return cand
                except OSError:
                    continue
            else:
                return cand
    return None


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


def _normalize_power(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() not in ("off", "false", "0", "disabled")
    if isinstance(val, (int, float)):
        return bool(val)
    return True


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
        "power": True,
        "brightness": 100,
        "night_mode": False,
        "night_start": "23:00",
        "night_end": "07:00",
        "night_brightness": 10,
    }
    if os.path.exists(SCREEN_STATE_FILE):
        try:
            with open(SCREEN_STATE_FILE) as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    state.update(loaded)
        except (json.JSONDecodeError, OSError):
            pass
    state["power"] = _normalize_power(state.get("power", True))
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
    if not _normalize_power(cfg.get("power", True)):
        return 0
    brightness = cfg.get("brightness", 100)
    if cfg.get("night_mode") and is_in_time_window(cfg.get("night_start", "23:00"), cfg.get("night_end", "07:00")):
        return int(cfg.get("night_brightness", 10))
    return int(brightness)


def set_fb_blank(power_on: bool) -> bool:
    """Controls framebuffer display scanout via sysfs fb0/blank.

    0 = FB_BLANK_UNBLANK (active display scanout enabled)
    4 = FB_BLANK_POWERDOWN (controller scanout powered down)
    """
    bases = []
    if HOST_SYS and os.path.exists(os.path.join(HOST_SYS, "class/graphics/fb0/blank")):
        bases.append(os.path.join(HOST_SYS, "class/graphics/fb0/blank"))
    bases.extend(["/host/sys/class/graphics/fb0/blank", "/sys/class/graphics/fb0/blank"])

    val = "0\n" if power_on else "4\n"
    success = False
    for p in bases:
        if os.path.exists(p):
            try:
                with open(p, "w") as f:
                    f.write(val)
                success = True
            except OSError:
                pass
    return success


def _apply_bl_power(bl_dir: str, power_on: bool):
    bl_power_path = os.path.join(bl_dir, "bl_power")
    if os.path.exists(bl_power_path):
        try:
            # Linux FB_BLANK_UNBLANK = 0 (power on), FB_BLANK_POWERDOWN = 4 (power off)
            with open(bl_power_path, "w") as f:
                f.write("0\n" if power_on else "4\n")
        except Exception:
            pass


def set_screen_brightness(pct):
    pct = max(0, min(100, int(pct)))
    set_fb_blank(pct > 0)
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
        _apply_bl_power(backlight_dir, pct > 0)
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
                    _apply_bl_power(fallback_dir, pct > 0)
                    return True
                except Exception as ex:
                    logger.warning(f"[SCREEN] Fallback write to {fallback_dir} also failed: {ex}")
        return False


def save_screen_state(updates: dict):
    global _cached_screen_state, _cached_screen_key
    state = get_screen_state()
    clean_updates = dict(updates)
    if "power" in clean_updates:
        clean_updates["power"] = _normalize_power(clean_updates["power"])
    elif "brightness" in clean_updates and int(clean_updates["brightness"]) > 0:
        clean_updates["power"] = True

    state.update(clean_updates)
    state["power"] = _normalize_power(state.get("power", True))
    atomic_write_json(SCREEN_STATE_FILE, state)
    try:
        st = os.stat(SCREEN_STATE_FILE)
        _cached_screen_key = (str(SCREEN_STATE_FILE), st.st_mtime_ns, st.st_size)
    except OSError:
        pass
    _cached_screen_state = state
    eff_bri = get_effective_brightness()
    set_screen_brightness(eff_bri)
    try:
        from backend.state import Z_STATE

        Z_STATE.ui_wake.set()
    except Exception:
        pass
    return dict(state)


def is_auxiliary_lcd_present() -> bool:
    """
    Checks if an embedded auxiliary LCD front-panel display is physically present.
    To avoid hijacking a generic PC's primary HDMI/DisplayPort monitor (e.g. 1920x1080),
    an auxiliary LCD is only considered present if:
    1. ENABLE_FB is enabled in configuration, AND
    2. A framebuffer character device exists, AND
    3. Either the host is a recognized appliance (is_zettlab_appliance()), OR its geometry is <= 800x480.
    """
    from backend.config import ENABLE_FB

    if not ENABLE_FB:
        return False
    fb_dev = find_fb_device(writable_only=False)
    if not fb_dev:
        return False

    try:
        from backend.hardware.fans import is_zettlab_appliance

        if is_zettlab_appliance():
            return True
    except Exception:
        pass

    for base in (
        os.path.join(HOST_SYS, "class/graphics/fb0") if HOST_SYS else None,
        "/host/sys/class/graphics/fb0",
        "/sys/class/graphics/fb0",
    ):
        if not base or not os.path.exists(base):
            continue
        v_path = os.path.join(base, "virtual_size")
        if os.path.exists(v_path):
            try:
                with open(v_path, encoding="utf-8", errors="replace") as f:
                    parts = [int(x.strip()) for x in f.read().split(",") if x.strip()]
                    if len(parts) == 2 and parts[0] > 0 and parts[1] > 0:
                        w, h = max(parts), min(parts)
                        return w <= 800 and h <= 480
            except Exception:
                pass
    return False
