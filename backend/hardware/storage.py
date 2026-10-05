import os
import json
import shutil
from backend.config import logger, POOL_PATH, HOST_PROC, HOST_SYS, DASH_LAYOUT_FILE
from backend.state import Z_STATE
from backend.hardware.disks import _discover_disks

def read_storage():
    try:
        u = shutil.disk_usage(POOL_PATH)
        total_gb = u.total / 1e9
        used_gb = u.used / 1e9
        pct = round(100 * u.used / u.total) if u.total else 0
        def fmt(g): return f"{g/1000:.0f}TB" if g >= 1000 else f"{g:.0f}GB"
        return {"used": fmt(used_gb), "total": fmt(total_gb), "pct": pct}
    except Exception:
        return {"used": "0GB", "total": "0GB", "pct": 0}

def read_uptime():
    try:
        with open(os.path.join(HOST_PROC, "uptime")) as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        return f"{h//24}d {h%24}h" if h >= 24 else f"{h}h {m}m"
    except Exception:
        return "?"

def detect_chassis_model():
    if Z_STATE.cached_chassis_model is not None:
        return Z_STATE.cached_chassis_model
    dmi_path = os.path.join(HOST_SYS, "class/dmi/id/product_name")
    if os.path.exists(dmi_path):
        try:
            prod = open(dmi_path).read().strip().lower()
            if "d8" in prod:
                Z_STATE.cached_chassis_model = "d8u"
                return Z_STATE.cached_chassis_model
            if "d6" in prod:
                Z_STATE.cached_chassis_model = "d6u"
                return Z_STATE.cached_chassis_model
            if "d4" in prod:
                Z_STATE.cached_chassis_model = "d4"
                return Z_STATE.cached_chassis_model
        except Exception as e:
            logger.debug(f"Silenced exception: {e}")

    disks = _discover_disks()
    count = len(disks)
    if count > 6:
        Z_STATE.cached_chassis_model = "d8u"
    elif count <= 4 and count > 0:
        Z_STATE.cached_chassis_model = "d4"
    else:
        Z_STATE.cached_chassis_model = "d6u"
    return Z_STATE.cached_chassis_model

def get_current_layout():
    layout = {
        "order": ["metric-storage", "metric-cpu", "metric-mem", "metric-fans", "metric-net", "metric-disks"],
        "vis": {
            "metric-storage": True,
            "metric-cpu": True,
            "metric-mem": True,
            "metric-fans": True,
            "metric-net": True,
            "metric-disks": True
        },
        "sizes": {},
        "clock_format": "24",
        "timezone": "America/New_York",
        "version": 1
    }
    if os.path.exists(DASH_LAYOUT_FILE):
        try:
            with open(DASH_LAYOUT_FILE, "r") as f:
                layout = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Silenced exception: {e}")
    return layout
