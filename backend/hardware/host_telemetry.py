"""
ZettNAS Toolkit - Host Platform & Hardware Telemetry (HAL)
Provides real-time DMI BIOS inspection, CPU architecture and governor status,
OS distribution and kernel identification, and GPU hardware transcode acceleration engine detection.
"""

import glob
import os
import platform
import time
from typing import Any

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, get_server_hostname, logger
from backend.ignored_errors import ignored

HOST_ETC = os.environ.get("HOST_ETC", "/host/etc")

_DMI_CACHE: dict[str, Any] = {}
_DMI_CACHE_TS = 0.0

_CPU_MODEL_CACHE = ""

_OS_DISTRO_CACHE = ""

_GPU_CACHE: dict[str, Any] = {}
_GPU_CACHE_TS = 0.0


def get_dmi_telemetry() -> dict[str, Any]:
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
                    with open(p, encoding="utf-8", errors="replace") as f:
                        return f.read().strip()
                except Exception:
                    ignored("backend.hardware.host_telemetry.get_dmi_telemetry._read_dmi")
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


def get_cpu_telemetry() -> dict[str, Any]:
    """Inspects CPU architecture, core count, scaling governor, and load averages."""
    global _CPU_MODEL_CACHE
    if not _CPU_MODEL_CACHE:
        for p in (os.path.join(HOST_PROC, "cpuinfo"), "/proc/cpuinfo"):
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if "model name" in line:
                                _CPU_MODEL_CACHE = line.split(":", 1)[1].strip()
                                break
                except Exception:
                    ignored("backend.hardware.host_telemetry.get_cpu_telemetry")
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
            with open(gp, encoding="utf-8", errors="replace") as f:
                governor = f.read().strip()
                break
        except Exception:
            ignored("backend.hardware.host_telemetry.get_cpu_telemetry")

    load_avg = [0.0, 0.0, 0.0]
    for lp in (os.path.join(HOST_PROC, "loadavg"), "/proc/loadavg"):
        if os.path.exists(lp):
            try:
                with open(lp, encoding="utf-8", errors="replace") as f:
                    parts = f.read().split()
                    load_avg = [float(parts[0]), float(parts[1]), float(parts[2])]
                break
            except Exception:
                ignored("backend.hardware.host_telemetry.get_cpu_telemetry")

    return {
        "model": _CPU_MODEL_CACHE,
        "cores": cores,
        "governor": governor,
        "load_avg": load_avg,
    }


def get_os_telemetry() -> dict[str, Any]:
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
                    with open(op, encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if line.startswith("PRETTY_NAME="):
                                _OS_DISTRO_CACHE = line.split("=", 1)[1].strip().strip('"').strip("'")
                                break
                            elif line.startswith("NAME=") and not _OS_DISTRO_CACHE:
                                _OS_DISTRO_CACHE = line.split("=", 1)[1].strip().strip('"').strip("'")
                except Exception:
                    ignored("backend.hardware.host_telemetry.get_os_telemetry")
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
                with open(up, encoding="utf-8", errors="replace") as f:
                    uptime_sec = float(f.read().split()[0])
                break
            except Exception:
                ignored("backend.hardware.host_telemetry.get_os_telemetry")

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


def get_gpu_telemetry() -> dict[str, Any]:
    """
    Detects hardware video transcode capabilities (Intel QuickSync, AMD VA-API, NVIDIA NVENC).
    Surfaces render node device paths and supported hardware video codecs.
    """
    global _GPU_CACHE, _GPU_CACHE_TS
    now = time.time()
    if _GPU_CACHE and (now - _GPU_CACHE_TS < 60):
        dyn = _sample_gpu_dynamic()
        res = dict(_GPU_CACHE)
        res.update(dyn)
        return res

    render_nodes = glob.glob(os.path.join(HOST_DEV, "dri/render*"))
    if not render_nodes and HOST_DEV in ("/dev", "/host/dev"):
        render_nodes = glob.glob("/host/dev/dri/render*") or glob.glob("/dev/dri/render*")

    cards = glob.glob(os.path.join(HOST_SYS, "class/drm/card*"))
    if not cards and HOST_SYS in ("/sys", "/host/sys"):
        cards = glob.glob("/host/sys/class/drm/card*") or glob.glob("/sys/class/drm/card*")

    vendor_id = ""
    device_id = ""
    driver = ""

    for c in cards:
        v_path = os.path.join(c, "device/vendor")
        if os.path.exists(v_path):
            try:
                with open(v_path, encoding="utf-8", errors="replace") as f:
                    vendor_id = f.read().strip().lower()
                with open(os.path.join(c, "device/device"), encoding="utf-8", errors="replace") as f:
                    device_id = f.read().strip().lower()
                driver_path = os.path.join(c, "device/driver")
                if os.path.islink(driver_path):
                    driver = os.path.basename(os.readlink(driver_path))
                break
            except Exception:
                ignored("backend.hardware.host_telemetry.get_gpu_telemetry")

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
    dyn = _sample_gpu_dynamic()
    res = dict(_GPU_CACHE)
    res.update(dyn)
    return res


_NPU_CACHE: dict[str, Any] = {}
_NPU_CACHE_TS = 0.0

_GPU_LAST_SAMPLE: dict[str, Any] = {"ts": 0.0, "rc6_ms": 0, "rc6_by_path": {}, "util_pct": 0.0}
_NPU_LAST_SAMPLE: dict[str, Any] = {"ts": 0.0, "busy_us": 0, "util_pct": 0.0}


def _sample_gpu_dynamic() -> dict[str, Any]:
    """Computes real-time GPU engine utilization % and active frequency from DRM sysfs."""
    global _GPU_LAST_SAMPLE
    now = time.time()
    cur_freq = 0
    max_freq = 2200

    freq_patterns = [
        os.path.join(HOST_SYS, "class/drm/card*/gt/gt*/rps_act_freq_mhz"),
        os.path.join(HOST_SYS, "class/drm/card*/gt_act_freq_mhz"),
        "/sys/class/drm/card*/gt/gt*/rps_act_freq_mhz",
        "/sys/class/drm/card*/gt_act_freq_mhz",
        "/host/sys/class/drm/card*/gt/gt*/rps_act_freq_mhz",
        "/host/sys/class/drm/card*/gt_act_freq_mhz",
    ]
    for pattern in freq_patterns:
        matches = glob.glob(pattern)
        for m in matches:
            try:
                with open(m, encoding="utf-8", errors="replace") as f:
                    val = int(f.read().strip())
                    if val > cur_freq:
                        cur_freq = val
            except Exception:
                ignored("backend.hardware.host_telemetry._sample_gpu_dynamic")

    max_freq_patterns = [
        os.path.join(HOST_SYS, "class/drm/card*/gt/gt*/rps_max_freq_mhz"),
        os.path.join(HOST_SYS, "class/drm/card*/gt_max_freq_mhz"),
        "/sys/class/drm/card*/gt/gt*/rps_max_freq_mhz",
        "/sys/class/drm/card*/gt_max_freq_mhz",
        "/host/sys/class/drm/card*/gt/gt*/rps_max_freq_mhz",
        "/host/sys/class/drm/card*/gt_max_freq_mhz",
    ]
    for pattern in max_freq_patterns:
        matches = glob.glob(pattern)
        for m in matches:
            try:
                with open(m, encoding="utf-8", errors="replace") as f:
                    val = int(f.read().strip())
                    if val > max_freq:
                        max_freq = val
            except Exception:
                ignored("backend.hardware.host_telemetry._sample_gpu_dynamic")

    rc6_patterns = [
        os.path.join(HOST_SYS, "class/drm/card*/gt/gt*/rc6_residency_ms"),
        "/sys/class/drm/card*/gt/gt*/rc6_residency_ms",
        "/host/sys/class/drm/card*/gt/gt*/rc6_residency_ms",
        os.path.join(HOST_SYS, "class/drm/card*/power/rc6_residency_ms"),
        "/sys/class/drm/card*/power/rc6_residency_ms",
        "/host/sys/class/drm/card*/power/rc6_residency_ms",
    ]
    rc6_files = []
    for pattern in rc6_patterns:
        for m in glob.glob(pattern):
            if m not in rc6_files:
                rc6_files.append(m)

    rc6_by_path = _GPU_LAST_SAMPLE.get("rc6_by_path", {})
    last_ts = _GPU_LAST_SAMPLE.get("ts", 0.0)
    dt_ms = (now - last_ts) * 1000.0 if last_ts > 0 else 0.0

    util_pct = _GPU_LAST_SAMPLE.get("util_pct", 0.0)
    active_utils = []

    for rf in rc6_files:
        try:
            with open(rf, encoding="utf-8", errors="replace") as f:
                rc6_val = int(f.read().strip())
        except Exception:
            continue

        if last_ts > 0 and dt_ms >= 400.0 and rf in rc6_by_path:
            last_rc6 = rc6_by_path[rf]
            d_rc6 = rc6_val - last_rc6
            if d_rc6 >= 0:
                busy_ratio = 1.0 - (d_rc6 / dt_ms)
                tile_util = round(max(0.0, min(100.0, busy_ratio * 100.0)), 1)
                active_utils.append(tile_util)
        rc6_by_path[rf] = rc6_val

    if active_utils:
        util_pct = max(active_utils)
        _GPU_LAST_SAMPLE["util_pct"] = util_pct
        _GPU_LAST_SAMPLE["ts"] = now
        _GPU_LAST_SAMPLE["rc6_by_path"] = rc6_by_path
    elif last_ts == 0.0:
        _GPU_LAST_SAMPLE["ts"] = now
        _GPU_LAST_SAMPLE["rc6_by_path"] = rc6_by_path

    # Busy time comes only from RC6 residency; without it the load is unknown (None), not 0
    return {
        "util_pct": util_pct if rc6_files else None,
        "cur_freq_mhz": cur_freq,
        "max_freq_mhz": max_freq,
    }


def _sample_npu_dynamic() -> dict[str, Any]:
    """Computes real-time NPU active compute % and frequency from Intel VPU / accel sysfs."""
    global _NPU_LAST_SAMPLE
    now = time.time()
    cur_freq = 0
    max_freq = 1400
    power_state = "D3hot"
    memory_bytes = 0

    accel_dirs = glob.glob(os.path.join(HOST_SYS, "class/accel/accel*/device"))
    if not accel_dirs and HOST_SYS in ("/sys", "/host/sys"):
        accel_dirs = glob.glob("/host/sys/class/accel/accel*/device") or glob.glob("/sys/class/accel/accel*/device")

    if accel_dirs:
        dev_dir = accel_dirs[0]
        try:
            fp = os.path.join(dev_dir, "npu_current_frequency_mhz")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="replace") as f:
                    cur_freq = int(f.read().strip())
        except Exception:
            ignored("backend.hardware.host_telemetry._sample_npu_dynamic")

        try:
            fp = os.path.join(dev_dir, "npu_max_frequency_mhz")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="replace") as f:
                    max_freq = int(f.read().strip())
        except Exception:
            ignored("backend.hardware.host_telemetry._sample_npu_dynamic")

        try:
            fp = os.path.join(dev_dir, "power_state")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="replace") as f:
                    power_state = f.read().strip()
        except Exception:
            ignored("backend.hardware.host_telemetry._sample_npu_dynamic")

        try:
            fp = os.path.join(dev_dir, "npu_memory_utilization")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="replace") as f:
                    memory_bytes = int(f.read().strip())
        except Exception:
            ignored("backend.hardware.host_telemetry._sample_npu_dynamic")

        busy_us = None
        try:
            fp = os.path.join(dev_dir, "npu_busy_time_us")
            if os.path.exists(fp):
                with open(fp, encoding="utf-8", errors="replace") as f:
                    busy_us = int(f.read().strip())
        except Exception:
            ignored("backend.hardware.host_telemetry._sample_npu_dynamic")

        util_pct = _NPU_LAST_SAMPLE["util_pct"]
        if busy_us is not None:
            last_ts = _NPU_LAST_SAMPLE["ts"]
            last_busy = _NPU_LAST_SAMPLE["busy_us"]
            if last_ts > 0:
                dt_us = (now - last_ts) * 1_000_000.0
                d_busy = busy_us - last_busy
                if dt_us >= 400_000.0 and d_busy >= 0:
                    util_pct = round(max(0.0, min(100.0, (d_busy / dt_us) * 100.0)), 1)
                    _NPU_LAST_SAMPLE["util_pct"] = util_pct
                    _NPU_LAST_SAMPLE["ts"] = now
                    _NPU_LAST_SAMPLE["busy_us"] = busy_us
            else:
                _NPU_LAST_SAMPLE["ts"] = now
                _NPU_LAST_SAMPLE["busy_us"] = busy_us
        else:
            _NPU_LAST_SAMPLE["ts"] = now

        if busy_us is None:
            util_pct = None  # the driver does not report busy time: unknown, not 0
    else:
        util_pct = 0.0

    return {
        "util_pct": util_pct,
        "cur_freq_mhz": cur_freq,
        "max_freq_mhz": max_freq,
        "power_state": power_state,
        "memory_bytes": memory_bytes,
    }


def get_npu_telemetry() -> dict[str, Any]:
    """
    Detects dedicated Neural Processing Unit (NPU) AI acceleration hardware (Intel AI Boost, AMD Ryzen AI).
    Surfaces driver status, clock rates, hardware scheduler, and supported inference frameworks.
    """
    global _NPU_CACHE, _NPU_CACHE_TS
    now = time.time()
    if _NPU_CACHE and (now - _NPU_CACHE_TS < 60):
        dyn = _sample_npu_dynamic()
        res = dict(_NPU_CACHE)
        res.update(dyn)
        return res

    accel_nodes = glob.glob(os.path.join(HOST_DEV, "accel/accel*"))
    if not accel_nodes and HOST_DEV in ("/dev", "/host/dev"):
        accel_nodes = glob.glob("/host/dev/accel/accel*") or glob.glob("/dev/accel/accel*")

    accel_sys = glob.glob(os.path.join(HOST_SYS, "class/accel/accel*"))
    if not accel_sys and HOST_SYS in ("/sys", "/host/sys"):
        accel_sys = glob.glob("/host/sys/class/accel/accel*") or glob.glob("/sys/class/accel/accel*")

    vendor_id = ""
    device_id = ""
    driver = ""
    max_freq = 0
    cur_freq = 0
    sched_mode = ""

    for node in accel_sys:
        dev_dir = os.path.join(node, "device")
        if os.path.exists(dev_dir):
            try:
                v_path = os.path.join(dev_dir, "vendor")
                if os.path.exists(v_path):
                    with open(v_path, encoding="utf-8", errors="replace") as f:
                        vendor_id = f.read().strip().lower()
                d_path = os.path.join(dev_dir, "device")
                if os.path.exists(d_path):
                    with open(d_path, encoding="utf-8", errors="replace") as f:
                        device_id = f.read().strip().lower()
                dr_path = os.path.join(dev_dir, "driver")
                if os.path.islink(dr_path):
                    driver = os.path.basename(os.readlink(dr_path))

                freq_max_path = os.path.join(dev_dir, "npu_max_frequency_mhz")
                if os.path.exists(freq_max_path):
                    with open(freq_max_path, encoding="utf-8", errors="replace") as f:
                        max_freq = int(f.read().strip())

                freq_cur_path = os.path.join(dev_dir, "npu_current_frequency_mhz")
                if os.path.exists(freq_cur_path):
                    with open(freq_cur_path, encoding="utf-8", errors="replace") as f:
                        cur_freq = int(f.read().strip())

                sched_path = os.path.join(dev_dir, "sched_mode")
                if os.path.exists(sched_path):
                    with open(sched_path, encoding="utf-8", errors="replace") as f:
                        sched_mode = f.read().strip()
                break
            except Exception:
                ignored("backend.hardware.host_telemetry.get_npu_telemetry")

    if vendor_id == "0x8086" or driver == "intel_vpu":
        vendor_name = "Intel"
        model_name = "Intel AI Boost NPU (Meteor Lake VPU 3720)"
        if device_id == "0x7d1d":
            model_name = "Intel AI Boost NPU (Meteor Lake VPU 3720)"
        elif device_id in ("0x643e", "0x643d"):
            model_name = "Intel AI Boost NPU (Lunar Lake / Arrow Lake)"
        acceleration = "Intel OpenVINO • ONNX Runtime • DirectML"
        frameworks = ["OpenVINO", "ONNX Runtime", "DirectML", "PyTorch IPEX"]
    elif vendor_id == "0x1022" or "xdna" in driver.lower() or "amd" in driver.lower():
        vendor_name = "AMD"
        model_name = "AMD Ryzen AI NPU (XDNA)"
        acceleration = "AMD Ryzen AI Software • ONNX Runtime"
        frameworks = ["Ryzen AI", "ONNX Runtime", "Vitis AI"]
    else:
        vendor_name = "None"
        model_name = "No NPU Detected"
        acceleration = "N/A"
        frameworks = []

    present = bool(accel_nodes or accel_sys or (vendor_id and vendor_id != "None"))
    active_node = (
        accel_nodes[0] if accel_nodes else (f"/dev/accel/{os.path.basename(accel_sys[0])}" if accel_sys else "")
    )

    _NPU_CACHE = {
        "present": present,
        "vendor": vendor_name if present else "None",
        "model": model_name,
        "driver": driver or ("intel_vpu" if vendor_name == "Intel" else ""),
        "acceleration": acceleration,
        "render_node": active_node,
        "max_freq_mhz": max_freq,
        "cur_freq_mhz": cur_freq,
        "sched_mode": sched_mode,
        "frameworks": frameworks,
        "ready": present,
    }
    _NPU_CACHE_TS = now
    dyn = _sample_npu_dynamic()
    res = dict(_NPU_CACHE)
    res.update(dyn)
    return res


def clear_telemetry_cache():
    """Test helper to invalidate cached hardware state."""
    global \
        _DMI_CACHE, \
        _DMI_CACHE_TS, \
        _CPU_MODEL_CACHE, \
        _OS_DISTRO_CACHE, \
        _GPU_CACHE, \
        _GPU_CACHE_TS, \
        _NPU_CACHE, \
        _NPU_CACHE_TS, \
        _GPU_LAST_SAMPLE, \
        _NPU_LAST_SAMPLE
    _DMI_CACHE = {}
    _DMI_CACHE_TS = 0.0
    _CPU_MODEL_CACHE = ""
    _OS_DISTRO_CACHE = ""
    _GPU_CACHE = {}
    _GPU_CACHE_TS = 0.0
    _NPU_CACHE = {}
    _NPU_CACHE_TS = 0.0
    _GPU_LAST_SAMPLE = {"ts": 0.0, "rc6_ms": 0, "rc6_by_path": {}, "util_pct": 0.0}
    _NPU_LAST_SAMPLE = {"ts": 0.0, "busy_us": 0, "util_pct": 0.0}
