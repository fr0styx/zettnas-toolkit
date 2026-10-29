"""
Kernel, Hardware Buses & Sysfs Telemetry for ZettNAS Toolkit.
Collects categorized kernel dmesg, CPU throttling counters, PCI/USB buses,
and sysfs hwmon attributes safely and quickly.
"""

import glob
import os
import re
import subprocess
import time
from typing import Any, Optional

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, logger
from backend.ignored_errors import ignored


def get_categorized_dmesg(max_lines: int = 300) -> dict[str, Any]:
    """
    Executes dmesg with a strict timeout and extracts hardware-critical alerts:
    thermal throttling, PCIe AER, I/O errors, memory faults, and crash logs.
    """
    cmd = ["dmesg", "-T", "--level=emerg,alert,crit,err,warn"]
    lines: list[str] = []
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0 and res.stdout:
            lines = res.stdout.strip().splitlines()
        else:
            # Fallback to plain dmesg if -T or --level is not supported on busybox
            fallback = subprocess.run(
                ["dmesg"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if fallback.returncode == 0 and fallback.stdout:
                lines = fallback.stdout.strip().splitlines()
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError) as e:
        logger.debug(f"[DIAGNOSTICS] dmesg collection skipped: {e}")
        return {"available": False, "error": str(e), "alerts": [], "recent_lines": []}

    error_patterns = [
        re.compile(r"(thermal|throttl|overheat|cpu\d+: core temperature above threshold)", re.IGNORECASE),
        re.compile(r"(pcie.*aer|advanced error reporting|uncorrectable)", re.IGNORECASE),
        re.compile(r"(i/o error|ata\d+|blk_update_request|buffer i/o error)", re.IGNORECASE),
        re.compile(r"(out of memory|oom-killer|killed process)", re.IGNORECASE),
        re.compile(r"(machine check exception|mce|hardware error)", re.IGNORECASE),
        re.compile(r"(btrfs: error|corrupt|checksum error|failed to read)", re.IGNORECASE),
    ]

    alerts: list[dict[str, str]] = []
    for line in lines:
        for pat in error_patterns:
            if pat.search(line):
                alerts.append(
                    {
                        "category": pat.pattern.split("(")[1].split("|")[0],
                        "line": line.strip(),
                    }
                )
                break

    return {
        "available": True,
        "total_lines_inspected": len(lines),
        "alerts_detected_count": len(alerts),
        "critical_alerts": alerts[-100:],
        "recent_lines": lines[-max_lines:],
    }


def get_cpu_telemetry() -> dict[str, Any]:
    """
    Inspects /proc/cpuinfo and /sys/devices/system/cpu for governors, microcode,
    and thermal throttling counters.
    """
    cpu_info: dict[str, Any] = {
        "model_name": "Unknown",
        "microcode": "Unknown",
        "governors": {},
        "thermal_throttling": {},
        "virtualization_flags": [],
    }

    # 1. /proc/cpuinfo
    cpuinfo_path = (
        os.path.join(HOST_PROC, "cpuinfo") if os.path.exists(os.path.join(HOST_PROC, "cpuinfo")) else "/proc/cpuinfo"
    )
    if os.path.exists(cpuinfo_path):
        try:
            with open(cpuinfo_path) as f:
                for line in f:
                    if "model name" in line and cpu_info["model_name"] == "Unknown":
                        cpu_info["model_name"] = line.split(":", 1)[1].strip()
                    elif "microcode" in line and cpu_info["microcode"] == "Unknown":
                        cpu_info["microcode"] = line.split(":", 1)[1].strip()
                    elif line.startswith("flags") or line.startswith("Features"):
                        flags = line.split(":", 1)[1].strip().split()
                        virt_flags = [fl for fl in flags if fl in ("vmx", "svm", "aes", "avx", "avx2", "avx512f")]
                        if virt_flags and not cpu_info["virtualization_flags"]:
                            cpu_info["virtualization_flags"] = virt_flags
        except Exception as e:
            logger.debug(f"[DIAGNOSTICS] Failed to read cpuinfo: {e}")

    # 2. Scaling governors
    sys_cpu_dir = os.path.join(HOST_SYS, "devices/system/cpu")
    if os.path.exists(sys_cpu_dir):
        gov_files = glob.glob(os.path.join(sys_cpu_dir, "cpu*/cpufreq/scaling_governor"))
        for gf in gov_files:
            try:
                cpu_id = gf.split("/")[-3]
                with open(gf) as f:
                    cpu_info["governors"][cpu_id] = f.read().strip()
            except Exception:
                ignored("backend.hardware.kernel_telemetry.get_cpu_telemetry")

        # 3. Thermal throttling counters
        throttle_files = glob.glob(os.path.join(sys_cpu_dir, "cpu*/thermal_throttle/*"))
        for tf in throttle_files:
            try:
                parts = tf.split("/")
                cpu_id, attr = parts[-3], parts[-1]
                with open(tf) as f:
                    val = f.read().strip()
                if cpu_id not in cpu_info["thermal_throttling"]:
                    cpu_info["thermal_throttling"][cpu_id] = {}
                cpu_info["thermal_throttling"][cpu_id][attr] = int(val) if val.isdigit() else val
            except Exception:
                ignored("backend.hardware.kernel_telemetry.get_cpu_telemetry")

    return cpu_info


def get_hardware_buses() -> dict[str, Any]:
    """
    Summarizes PCI and USB bus topologies.
    """
    pci_devs = []
    pci_dir = os.path.join(HOST_SYS, "bus/pci/devices")
    if os.path.exists(pci_dir):
        try:
            for d in os.listdir(pci_dir):
                d_path = os.path.join(pci_dir, d)
                vendor, device, cls = "", "", ""
                try:
                    with open(os.path.join(d_path, "vendor")) as f:
                        vendor = f.read().strip()
                    with open(os.path.join(d_path, "device")) as f:
                        device = f.read().strip()
                    with open(os.path.join(d_path, "class")) as f:
                        cls = f.read().strip()
                except Exception:
                    ignored("backend.hardware.kernel_telemetry.get_hardware_buses")
                pci_devs.append({"slot": d, "vendor": vendor, "device": device, "class": cls})
        except Exception as e:
            logger.debug(f"[DIAGNOSTICS] Failed reading PCI bus: {e}")

    usb_devs = []
    usb_dir = os.path.join(HOST_SYS, "bus/usb/devices")
    if os.path.exists(usb_dir):
        try:
            for d in os.listdir(usb_dir):
                d_path = os.path.join(usb_dir, d)
                prod, mfr = "", ""
                try:
                    if os.path.exists(os.path.join(d_path, "product")):
                        with open(os.path.join(d_path, "product")) as f:
                            prod = f.read().strip()
                    if os.path.exists(os.path.join(d_path, "manufacturer")):
                        with open(os.path.join(d_path, "manufacturer")) as f:
                            mfr = f.read().strip()
                except Exception:
                    ignored("backend.hardware.kernel_telemetry.get_hardware_buses")
                if prod or mfr:
                    usb_devs.append({"bus_id": d, "product": prod, "manufacturer": mfr})
        except Exception as e:
            logger.debug(f"[DIAGNOSTICS] Failed reading USB bus: {e}")

    power_supplies = []
    psy_dir = os.path.join(HOST_SYS, "class/power_supply")
    if os.path.exists(psy_dir):
        try:
            for p in sorted(os.listdir(psy_dir)):
                p_path = os.path.join(psy_dir, p)
                if os.path.isdir(p_path):
                    entry = {"name": p}
                    for attr in ("type", "online", "status", "capacity", "model_name", "manufacturer", "voltage_now"):
                        attr_f = os.path.join(p_path, attr)
                        if os.path.isfile(attr_f):
                            try:
                                with open(attr_f) as f:
                                    entry[attr] = f.read().strip()
                            except Exception:
                                ignored("backend.hardware.kernel_telemetry.get_hardware_buses")
                    power_supplies.append(entry)
        except Exception as e:
            logger.debug(f"[DIAGNOSTICS] Failed reading power_supply class: {e}")

    hidraw_devs = []
    hidraw_dir = os.path.join(HOST_SYS, "class/hidraw")
    if os.path.exists(hidraw_dir):
        try:
            for h in sorted(os.listdir(hidraw_dir)):
                uevent_f = os.path.join(hidraw_dir, h, "device/uevent")
                entry = {"node": h}
                if os.path.isfile(uevent_f):
                    try:
                        with open(uevent_f) as f:
                            for line in f:
                                if "=" in line:
                                    k, v = line.strip().split("=", 1)
                                    if k in ("HID_ID", "HID_NAME", "HID_UNIQ", "DRIVER"):
                                        entry[k] = v
                    except Exception:
                        ignored("backend.hardware.kernel_telemetry.get_hardware_buses")
                hidraw_devs.append(entry)
        except Exception as e:
            logger.debug(f"[DIAGNOSTICS] Failed reading hidraw class: {e}")

    return {
        "pci_devices_count": len(pci_devs),
        "pci_devices": pci_devs[:40],
        "usb_devices_count": len(usb_devs),
        "usb_devices": usb_devs,
        "power_supplies_count": len(power_supplies),
        "power_supplies": power_supplies,
        "hidraw_devices_count": len(hidraw_devs),
        "hidraw_devices": hidraw_devs,
    }


def get_hwmon_details() -> list[dict[str, Any]]:
    """
    Directly queries all sysfs hwmon nodes for fan RPMs, PWM values, and temperatures.
    """
    hwmon_list = []
    hwmon_base = os.path.join(HOST_SYS, "class/hwmon")
    if not os.path.exists(hwmon_base):
        return hwmon_list

    try:
        dirs = sorted(glob.glob(os.path.join(hwmon_base, "hwmon*")))
        for hdir in dirs:
            h_name = "unknown"
            name_file = os.path.join(hdir, "name")
            if os.path.exists(name_file):
                try:
                    with open(name_file) as f:
                        h_name = f.read().strip()
                except Exception:
                    ignored("backend.hardware.kernel_telemetry.get_hwmon_details")

            sensors: dict[str, Any] = {"name": h_name, "path": hdir, "attributes": {}}
            for attr_file in glob.glob(os.path.join(hdir, "*_input")) + glob.glob(os.path.join(hdir, "pwm*")):
                base_attr = os.path.basename(attr_file)
                try:
                    with open(attr_file) as f:
                        val = f.read().strip()
                    sensors["attributes"][base_attr] = int(val) if val.isdigit() else val
                except Exception:
                    ignored("backend.hardware.kernel_telemetry.get_hwmon_details")
            hwmon_list.append(sensors)
    except Exception as e:
        logger.debug(f"[DIAGNOSTICS] Failed reading hwmon: {e}")

    return hwmon_list


def get_peripheral_status() -> dict[str, Any]:
    """
    Checks physical appliance peripheral availability and read/write access permissions.
    """

    def _check_dev(path_candidates: list[str]) -> dict[str, Any]:
        for p in path_candidates:
            if os.path.exists(p):
                accessible = os.access(p, os.R_OK | os.W_OK)
                return {"present": True, "path": p, "accessible": accessible}
        return {"present": False, "path": path_candidates[0] if path_candidates else "", "accessible": False}

    return {
        "framebuffer_lcd_fb0": _check_dev([os.path.join(HOST_DEV, "fb0"), "/dev/fb0"]),
        "argb_serial_ttyACM0": _check_dev([os.path.join(HOST_DEV, "ttyACM0"), "/dev/ttyACM0"]),
        "intel_npu_accel0": _check_dev([os.path.join(HOST_DEV, "accel/accel0"), "/dev/accel/accel0"]),
        "gpu_render_d128": _check_dev([os.path.join(HOST_DEV, "dri/renderD128"), "/dev/dri/renderD128"]),
        "dev_mem": _check_dev([os.path.join(HOST_DEV, "mem"), "/dev/mem"]),
        "kvm_acceleration_node": _check_dev([os.path.join(HOST_DEV, "kvm"), "/dev/kvm"]),
    }


def get_media_slots_telemetry() -> dict[str, Any]:
    """Captures front SD/TF multi-LUN card slot insertion and SCSI polling states."""
    try:
        from backend.config import BUTTON_CFG_FILE
        from backend.fsutil import read_json
        from backend.services.copy_engine import _EJECTED_SLOTS, read_media_slots
        from backend.state import Z_STATE

        slots = read_media_slots()
        btn_cfg = read_json(BUTTON_CFG_FILE, {})

        # Check SCSI polling msecs
        polling_states = {}
        for slot_name in ("sd", "tf"):
            dev_name = slots.get(slot_name, {}).get("dev")
            if dev_name:
                poll_f = os.path.join(HOST_SYS, f"block/{dev_name}/events_poll_msecs")
                if os.path.exists(poll_f):
                    try:
                        with open(poll_f) as f:
                            polling_states[dev_name] = f.read().strip()
                    except Exception:
                        ignored("backend.hardware.kernel_telemetry.get_media_slots_telemetry")

        return {
            "slots": slots,
            "ejected_slots": list(_EJECTED_SLOTS),
            "scsi_polling_msecs": polling_states,
            "auto_ingest_enabled": btn_cfg.get("auto_ingest", False),
            "pending_ingest": getattr(Z_STATE, "pending_ingest", None),
            "pending_usb": getattr(Z_STATE, "pending_usb", None),
            "copy_active": getattr(Z_STATE, "copy_active", False),
        }
    except Exception as e:
        return {"error": str(e)}


def collect_kernel_telemetry() -> dict[str, Any]:
    """
    Main aggregator for kernel, CPU, buses, and hardware sensors.
    """
    t0 = time.time()
    from backend.hardware.host_telemetry import get_gpu_telemetry, get_npu_telemetry

    return {
        "collection_time_seconds": round(time.time() - t0, 3),
        "dmesg_analysis": get_categorized_dmesg(max_lines=300),
        "cpu_telemetry": get_cpu_telemetry(),
        "gpu_telemetry": get_gpu_telemetry(),
        "npu_telemetry": get_npu_telemetry(),
        "hardware_buses": get_hardware_buses(),
        "hwmon_sensors": get_hwmon_details(),
        "media_slots": get_media_slots_telemetry(),
        "peripherals": get_peripheral_status(),
    }
