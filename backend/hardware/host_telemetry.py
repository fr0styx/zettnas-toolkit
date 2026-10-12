"""
ZettNAS Toolkit - Host Platform & Hardware Telemetry (HAL)
Provides real-time DMI BIOS inspection, CPU architecture and governor status,
OS distribution and kernel identification, and GPU hardware transcode acceleration engine detection.
"""

import glob
import os
import platform
import time
from typing import Any, Dict

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, get_server_hostname, logger

HOST_ETC = os.environ.get("HOST_ETC", "/host/etc")

_DMI_CACHE: Dict[str, Any] = {}
_DMI_CACHE_TS = 0.0

_CPU_MODEL_CACHE = ""

_OS_DISTRO_CACHE = ""

_GPU_CACHE: Dict[str, Any] = {}
_GPU_CACHE_TS = 0.0


def get_dmi_telemetry() -> Dict[str, Any]:
    """Reads motherboard model, vendor, and BIOS firmware from sysfs DMI."""
    global _DMI_CACHE, _DMI_CACHE_TS
    now = time.time()
    if _DMI_CACHE and (now - _DMI_CACHE_TS < 300):
        return _DMI_CACHE

    def _read_dmi(name: str) -> str:
        for b in (os.path.join(HOST_SYS, "class/dmi/id"), "/sys/class/dmi/id", "/host/sys/class/dmi/id"):
            p = os.path.join(b, name)
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        return f.read().strip()
                except Exception:
                    pass
        return ""

    vendor = _read_dmi("sys_vendor") or "Zettlab"
    board = _read_dmi("board_name") or _read_dmi("product_name") or "Standard PC"
    bios_version = _read_dmi("bios_version") or "N/A"
    bios_date = _read_dmi("bios_date") or ""
    product = _read_dmi("product_name") or board

    _DMI_CACHE = {
        "vendor": vendor,
        "board": board,
        "product": product,
        "bios_version": bios_version,
        "bios_date": bios_date,
    }
    _DMI_CACHE_TS = now
    return _DMI_CACHE


def get_cpu_telemetry() -> Dict[str, Any]:
    """Inspects CPU architecture, core count, scaling governor, and load averages."""
    global _CPU_MODEL_CACHE
    if not _CPU_MODEL_CACHE:
        for p in (os.path.join(HOST_PROC, "cpuinfo"), "/proc/cpuinfo"):
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if "model name" in line:
                                _CPU_MODEL_CACHE = line.split(":", 1)[1].strip()
                                break
                except Exception:
                    pass
                if _CPU_MODEL_CACHE:
                    break
        if not _CPU_MODEL_CACHE:
            _CPU_MODEL_CACHE = platform.processor() or "x86_64"

    cores = os.cpu_count() or 1

    governor = "Unknown"
    for gp in glob.glob(os.path.join(HOST_SYS, "devices/system/cpu/cpu*/cpufreq/scaling_governor")) + glob.glob(
        "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
    ):
        try:
            with open(gp, "r", encoding="utf-8", errors="replace") as f:
                governor = f.read().strip()
                break
        except Exception:
            pass

    load_avg = [0.0, 0.0, 0.0]
    for lp in (os.path.join(HOST_PROC, "loadavg"), "/proc/loadavg"):
        if os.path.exists(lp):
            try:
                with open(lp, "r", encoding="utf-8", errors="replace") as f:
                    parts = f.read().split()
                    load_avg = [float(parts[0]), float(parts[1]), float(parts[2])]
                break
            except Exception:
                pass

    return {
        "model": _CPU_MODEL_CACHE,
        "cores": cores,
        "governor": governor,
        "load_avg": load_avg,
    }


def get_os_telemetry() -> Dict[str, Any]:
    """Resolves host OS distribution, kernel version, formatted uptime, and hostname."""
    global _OS_DISTRO_CACHE
    if not _OS_DISTRO_CACHE:
        for op in (
            os.path.join(HOST_ETC, "os-release"),
            "/host/etc/os-release",
            "/etc/os-release",
        ):
            if os.path.exists(op):
                try:
                    with open(op, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if line.startswith("PRETTY_NAME="):
                                _OS_DISTRO_CACHE = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
                            elif line.startswith("NAME=") and not _OS_DISTRO_CACHE:
                                _OS_DISTRO_CACHE = line.split("=", 1)[1].strip().strip('"').strip("'")
                except Exception:
                    pass
                if _OS_DISTRO_CACHE:
                    break

        kernel_rel = platform.release()
        if "unraid" in kernel_rel.lower() and "unraid" not in (_OS_DISTRO_CACHE or "").lower():
            _OS_DISTRO_CACHE = "Unraid OS"
        elif not _OS_DISTRO_CACHE:
            _OS_DISTRO_CACHE = "Linux"

    uptime_sec = 0.0
    for up in (os.path.join(HOST_PROC, "uptime"), "/proc/uptime"):
        if os.path.exists(up):
            try:
                with open(up, "r", encoding="utf-8", errors="replace") as f:
                    uptime_sec = float(f.read().split()[0])
                break
            except Exception:
                pass

    days = int(uptime_sec // 86400)
    hours = int((uptime_sec % 86400) // 3600)
    mins = int((uptime_sec % 3600) // 60)
    uptime_str = f"{days}d {hours}h {mins}m" if days > 0 else f"{hours}h {mins}m"

    return {
        "distro": _OS_DISTRO_CACHE,
        "kernel": platform.release(),
        "uptime_str": uptime_str,
        "uptime_sec": round(uptime_sec, 1),
        "hostname": get_server_hostname(),
    }


def get_gpu_telemetry() -> Dict[str, Any]:
    """
    Detects hardware video transcode capabilities (Intel QuickSync, AMD VA-API, NVIDIA NVENC).
    Surfaces render node device paths and supported hardware video codecs.
    """
    global _GPU_CACHE, _GPU_CACHE_TS
    now = time.time()
    if _GPU_CACHE and (now - _GPU_CACHE_TS < 60):
        return _GPU_CACHE

    render_nodes = (
        glob.glob(os.path.join(HOST_DEV, "dri/render*"))
        or glob.glob("/host/dev/dri/render*")
        or glob.glob("/dev/dri/render*")
    )
    cards = (
        glob.glob(os.path.join(HOST_SYS, "class/drm/card*"))
        or glob.glob("/host/sys/class/drm/card*")
        or glob.glob("/sys/class/drm/card*")
    )

    vendor_id = ""
    device_id = ""
    driver = ""

    for c in cards:
        v_path = os.path.join(c, "device/vendor")
        if os.path.exists(v_path):
            try:
                with open(v_path, "r", encoding="utf-8", errors="replace") as f:
                    vendor_id = f.read().strip().lower()
                with open(os.path.join(c, "device/device"), "r", encoding="utf-8", errors="replace") as f:
                    device_id = f.read().strip().lower()
                driver_path = os.path.join(c, "device/driver")
                if os.path.islink(driver_path):
                    driver = os.path.basename(os.readlink(driver_path))
                break
            except Exception:
                pass

    if vendor_id == "0x8086":
        vendor_name = "Intel"
        model_name = "Intel Arc / QuickSync Video"
        if device_id in ("0x7d55", "0x7d45", "0x7d65"):
            model_name = "Intel Arc Graphics (Meteor Lake-P GT1)"
        elif device_id in ("0x4690", "0x4680", "0x4626"):
            model_name = "Intel UHD Graphics 770 (Alder Lake)"
        elif device_id in ("0x9a49", "0x9a40"):
            model_name = "Intel Iris Xe Graphics (Tiger Lake)"
        elif device_id in ("0x56a0", "0x56a1", "0x5690"):
            model_name = "Intel Arc A770 / A750 / A380"
        acceleration = "Intel QuickSync Video (QSV) • VA-API"
        codecs = ["AV1", "HEVC 10-bit", "H.264", "VP9"]
    elif vendor_id == "0x1002":
        vendor_name = "AMD"
        model_name = "AMD Radeon Graphics / VA-API"
        acceleration = "AMD VA-API • AMF"
        codecs = ["HEVC", "H.264", "AV1"]
    elif vendor_id == "0x10de" or os.path.exists("/dev/nvidia0"):
        vendor_name = "NVIDIA"
        model_name = "NVIDIA GeForce / NVENC"
        acceleration = "NVIDIA NVENC / NVDEC • CUDA"
        codecs = ["AV1", "HEVC 10-bit", "H.264"]
    else:
        vendor_name = "Generic / Virtual"
        model_name = "No Hardware Video Transcode Acceleration Detected"
        acceleration = "Software CPU Only"
        codecs = []

    has_render = len(render_nodes) > 0
    active_node = render_nodes[0] if render_nodes else ""

    _GPU_CACHE = {
        "present": has_render or bool(vendor_id),
        "vendor": vendor_name,
        "model": model_name,
        "driver": driver or "i915",
        "acceleration": acceleration,
        "render_node": active_node,
        "codecs": codecs,
        "ready": has_render,
    }
    _GPU_CACHE_TS = now
    return _GPU_CACHE


def clear_telemetry_cache():
    """Test helper to invalidate cached hardware state."""
    global _DMI_CACHE, _DMI_CACHE_TS, _CPU_MODEL_CACHE, _OS_DISTRO_CACHE, _GPU_CACHE, _GPU_CACHE_TS
    _DMI_CACHE = {}
    _DMI_CACHE_TS = 0.0
    _CPU_MODEL_CACHE = ""
    _OS_DISTRO_CACHE = ""
    _GPU_CACHE = {}
    _GPU_CACHE_TS = 0.0
