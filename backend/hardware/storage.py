import json
import os
import shutil

from backend.config import DASH_LAYOUT_FILE, HOST_PROC, HOST_SYS, POOL_PATH, logger
from backend.fsutil import read_json_cached
from backend.hardware.disks import _discover_disks
from backend.state import Z_STATE


def read_storage():
    try:
        u = shutil.disk_usage(POOL_PATH)
        total_gb = u.total / 1e9
        used_gb = u.used / 1e9
        pct = round(100 * u.used / u.total) if u.total else 0

        def fmt(g):
            return f"{g / 1000:.0f}TB" if g >= 1000 else f"{g:.0f}GB"

        engine = "Btrfs / OpenZFS"
        try:
            from backend.hardware.pal_storage import PlatformType, StoragePlatformDetector

            pt = StoragePlatformDetector.detect()
            if pt == PlatformType.UNRAID:
                engine = "Unraid (md/shfs)"
            elif pt == PlatformType.TRUENAS:
                engine = "OpenZFS"
            elif pt == PlatformType.PROXMOX:
                engine = "ZFS / LVM-Thin"
            elif pt == PlatformType.FYGOOS:
                engine = "FygoOS Storage Engine"
            elif pt == PlatformType.ZETTOS:
                engine = "ZettOS (ZFS / Btrfs Hybrid)"
            elif pt == PlatformType.UGOS:
                engine = "UGOS (mdadm / LVM / Btrfs)"
            elif pt == PlatformType.GENERIC_OBSERVER:
                engine = "Observer Telemetry Engine"
            else:
                engine = "Btrfs Native Subvolumes"
        except Exception:
            pass

        return {"used": fmt(used_gb), "total": fmt(total_gb), "pct": pct, "engine": engine}
    except Exception:
        return {"used": "0GB", "total": "0GB", "pct": 0, "engine": "Btrfs / OpenZFS"}


def read_uptime():
    try:
        with open(os.path.join(HOST_PROC, "uptime")) as f:
            secs = float(f.read().split()[0])
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        return f"{h // 24}d {h % 24}h" if h >= 24 else f"{h}h {m}m"
    except Exception:
        return "?"


def get_chassis_friendly_name(slug_or_model: str) -> str:
    """Returns a polished human-readable chassis name from a model slug or identifier."""
    if not slug_or_model:
        return "Standard / DIY Enclosure"
    s = str(slug_or_model).strip().lower()
    if s in ("d4", "wy110", "nas-4", "4-bay"):
        return "Zettlab D4 (4-Bay)"
    if s in ("d6u", "d6", "wy120", "nas-6", "6-bay"):
        return "Zettlab D6 Ultra (6-Bay)"
    if s in ("d8u", "d8", "wy140", "nas-8", "8-bay"):
        return "Zettlab D8 Ultra (8-Bay)"
    if "aoostar" in s or "wtr" in s:
        return "AOOSTAR WTR Enclosure"
    if "ugreen" in s or "dxp" in s:
        return "UGREEN DXP NAS"
    if "minisforum" in s:
        return "MINISFORUM NAS"
    if "tower" in s:
        return "Desktop Tower NAS"
    if "rack" in s:
        return "Enterprise Rackmount NAS"
    return slug_or_model.upper() if len(slug_or_model) <= 4 else slug_or_model


def _read_dmi_text(field: str) -> str:
    bases = [HOST_SYS, "/sys", "/host/sys"]
    for base in bases:
        if not base:
            continue
        p = os.path.join(base, "class/dmi/id", field)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                    if content and content.lower() != "default string":
                        return content
            except Exception:
                pass
    return ""


def detect_chassis_model(force: bool = False):
    if not force and Z_STATE.cached_chassis_model is not None:
        return Z_STATE.cached_chassis_model

    # 1. User manual bay mapping configuration override
    try:
        from backend.hardware.chassis import ChassisEngine

        cfg = ChassisEngine.load_bay_mapping_config()
        configured_bays = cfg.get("total_bays")
        configured_profile = cfg.get("profile")
        if configured_bays == 4 or configured_profile == "compact_dual":
            Z_STATE.cached_chassis_model = "d4"
            return "d4"
        if configured_bays == 8:
            Z_STATE.cached_chassis_model = "d8u"
            return "d8u"
        if configured_bays == 6:
            Z_STATE.cached_chassis_model = "d6u"
            return "d6u"
    except Exception as e:
        logger.debug(f"[detect_chassis_model] Bay config check ignored: {e}")

    # 2. Comprehensive DMI Hardware Identification
    prod = _read_dmi_text("product_name").lower()
    board = _read_dmi_text("board_name").lower()
    sku = _read_dmi_text("product_sku").lower()
    family = _read_dmi_text("product_family").lower()
    vendor = _read_dmi_text("sys_vendor").lower()
    board_vendor = _read_dmi_text("board_vendor").lower()

    combined_dmi = f"{prod} {board} {sku} {family} {vendor} {board_vendor}"

    # D4 Motherboard (WY110 / N100 4-bay) check
    if any(k in combined_dmi for k in ("wy110", "d4 ultra", "d4 pro", "nas-4")) or (
        "d4" in prod or "d4" in board or "d4" in sku
    ):
        Z_STATE.cached_chassis_model = "d4"
        return "d4"

    # D8 Motherboard (WY140 / 8-bay) check
    if any(k in combined_dmi for k in ("wy140", "d8 ultra", "d8u", "nas-8")) or (
        "d8" in prod or "d8" in board or "d8" in sku
    ):
        Z_STATE.cached_chassis_model = "d8u"
        return "d8u"

    # D6 Motherboard (WY120 / i3-N305 6-bay) check
    if any(k in combined_dmi for k in ("wy120", "d6 ultra", "d6u", "nas-6")) or (
        "d6" in prod or "d6" in board or "d6" in sku
    ):
        Z_STATE.cached_chassis_model = "d6u"
        return "d6u"

    # 3. Hardware Fan Topology Check (Physical Zettlab Appliance)
    # Zettlab D4 hardware has ONLY 1 chassis fan channel (pwm1) and 1 CPU fan (pwm3).
    # Zettlab D6U and D8 appliances have 2 chassis fan channels (pwm1 and pwm2) and 1 CPU fan (pwm3).
    is_zettlab_brand = "zettlab" in vendor or "zettlab" in board_vendor or "zettos" in family
    if is_zettlab_brand:
        pwm2_found = False
        pwm1_found = False
        for base_hwmon in (
            os.path.join(HOST_SYS, "class/hwmon") if HOST_SYS else None,
            "/sys/class/hwmon",
            "/host/sys/class/hwmon",
        ):
            if not base_hwmon or not os.path.exists(base_hwmon):
                continue
            try:
                for h in os.listdir(base_hwmon):
                    h_path = os.path.join(base_hwmon, h)
                    if os.path.exists(os.path.join(h_path, "pwm1")):
                        pwm1_found = True
                    if os.path.exists(os.path.join(h_path, "pwm2")):
                        pwm2_found = True
            except Exception:
                pass
        if pwm1_found and not pwm2_found:
            Z_STATE.cached_chassis_model = "d4"
            return "d4"

    # 4. Fallback: Physical Internal Bay Drive Count (Filter out M.2 NVMe and USB drives!)
    try:
        from backend.hardware.hal import DiskDiscoveryHAL

        records = DiskDiscoveryHAL.discover_physical_disks()
        bay_disks = [
            r
            for r in records
            if r.transport not in ("nvme", "usb") and not r.dev_name.startswith("nvme") and not r.removable
        ]
        count = len(bay_disks)
    except Exception:
        disks = _discover_disks()
        count = len([d for d in disks if not str(d.get("dev", "")).startswith("nvme") and d.get("role") != "os"])

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
            "metric-disks": True,
        },
        "sizes": {},
        "clock_format": "24",
        "timezone": "America/New_York",
        "version": 1,
    }
    loaded = read_json_cached(DASH_LAYOUT_FILE, default=None)
    if isinstance(loaded, dict):
        layout = loaded
    return layout
