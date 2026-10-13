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
from typing import Any, Dict, List, Optional

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, logger


def get_categorized_dmesg(max_lines: int = 300) -> Dict[str, Any]:
    """
    Executes dmesg with a strict timeout and extracts hardware-critical alerts:
    thermal throttling, PCIe AER, I/O errors, memory faults, and crash logs.
    """
    cmd = ["dmesg", "-T", "--level=emerg,alert,crit,err,warn"]
    lines: List[str] = []
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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

    alerts: List[Dict[str, str]] = []
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


def get_cpu_telemetry() -> Dict[str, Any]:
    """
    Inspects /proc/cpuinfo and /sys/devices/system/cpu for governors, microcode,
    and thermal throttling counters.
    """
    cpu_info: Dict[str, Any] = {
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
            with open(cpuinfo_path, "r") as f:
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
                with open(gf, "r") as f:
                    cpu_info["governors"][cpu_id] = f.read().strip()
            except Exception:
                pass

        # 3. Thermal throttling counters
        throttle_files = glob.glob(os.path.join(sys_cpu_dir, "cpu*/thermal_throttle/*"))
        for tf in throttle_files:
            try:
                parts = tf.split("/")
                cpu_id, attr = parts[-3], parts[-1]
                with open(tf, "r") as f:
                    val = f.read().strip()
                if cpu_id not in cpu_info["thermal_throttling"]:
                    cpu_info["thermal_throttling"][cpu_id] = {}
                cpu_info["thermal_throttling"][cpu_id][attr] = int(val) if val.isdigit() else val
            except Exception:
                pass

    return cpu_info


def get_hardware_buses() -> Dict[str, Any]:
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
                    with open(os.path.join(d_path, "vendor"), "r") as f:
                        vendor = f.read().strip()
                    with open(os.path.join(d_path, "device"), "r") as f:
                        device = f.read().strip()
                    with open(os.path.join(d_path, "class"), "r") as f:
                        cls = f.read().strip()
                except Exception:
                    pass
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
                        with open(os.path.join(d_path, "product"), "r") as f:
                            prod = f.read().strip()
                    if os.path.exists(os.path.join(d_path, "manufacturer")):
                        with open(os.path.join(d_path, "manufacturer"), "r") as f:
                            mfr = f.read().strip()
                except Exception:
                    pass
                if prod or mfr:
                    usb_devs.append({"bus_id": d, "product": prod, "manufacturer": mfr})
        except Exception as e:
            logger.debug(f"[DIAGNOSTICS] Failed reading USB bus: {e}")

    return {
        "pci_devices_count": len(pci_devs),
        "pci_devices": pci_devs[:40],
        "usb_devices_count": len(usb_devs),
        "usb_devices": usb_devs,
    }


def get_hwmon_details() -> List[Dict[str, Any]]:
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
                    with open(name_file, "r") as f:
                        h_name = f.read().strip()
                except Exception:
                    pass

            sensors: Dict[str, Any] = {"name": h_name, "path": hdir, "attributes": {}}
            for attr_file in glob.glob(os.path.join(hdir, "*_input")) + glob.glob(os.path.join(hdir, "pwm*")):
                base_attr = os.path.basename(attr_file)
                try:
                    with open(attr_file, "r") as f:
                        val = f.read().strip()
                    sensors["attributes"][base_attr] = int(val) if val.isdigit() else val
                except Exception:
                    pass
            hwmon_list.append(sensors)
    except Exception as e:
        logger.debug(f"[DIAGNOSTICS] Failed reading hwmon: {e}")

    return hwmon_list


def get_peripheral_status() -> Dict[str, Any]:
    """
    Checks physical appliance peripheral availability.
    """
    fb0 = os.path.exists(os.path.join(HOST_DEV, "fb0")) or os.path.exists("/dev/fb0")
    tty_acm = os.path.exists(os.path.join(HOST_DEV, "ttyACM0")) or os.path.exists("/dev/ttyACM0")
    npu_accel = os.path.exists(os.path.join(HOST_DEV, "accel/accel0")) or os.path.exists("/dev/accel/accel0")
    dri_render = os.path.exists(os.path.join(HOST_DEV, "dri/renderD128")) or os.path.exists("/dev/dri/renderD128")
    kvm_node = os.path.exists(os.path.join(HOST_DEV, "kvm")) or os.path.exists("/dev/kvm")

    return {
        "framebuffer_lcd_fb0": fb0,
        "argb_serial_ttyACM0": tty_acm,
        "intel_npu_accel0": npu_accel,
        "gpu_render_d128": dri_render,
        "kvm_acceleration_node": kvm_node,
    }


def collect_kernel_telemetry() -> Dict[str, Any]:
    """
    Main aggregator for kernel, CPU, buses, and hardware sensors.
    """
    t0 = time.time()
    return {
        "collection_time_seconds": round(time.time() - t0, 3),
        "dmesg_analysis": get_categorized_dmesg(max_lines=300),
        "cpu_telemetry": get_cpu_telemetry(),
        "hardware_buses": get_hardware_buses(),
        "hwmon_sensors": get_hwmon_details(),
        "peripherals": get_peripheral_status(),
    }
