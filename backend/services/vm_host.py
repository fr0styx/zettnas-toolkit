"""
What the host offers VMs: memory and CPU budget, KVM status, ISOs, bridges, USB
and PCI passthrough, UEFI firmware and vTPM.

Split out of backend/api/vms.py (ARC-01); the API re-exports these names.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import DATA_DIR, HOST_PROC, POOL_PATH, VM_ISO_DIR, logger
from backend.confirmations import require_confirmation
from backend.fsutil import atomic_write_json, read_json, resolve_within
from backend.services import vm_store
from backend.services.vm_engine import QmpEngine
from backend.state import Z_STATE, add_event


def _get_host_memory_bytes() -> int:
    """Read total host memory in bytes from /proc/meminfo or system state."""
    mem_info = "/host/proc/meminfo" if os.path.exists("/host/proc/meminfo") else "/proc/meminfo"
    if os.path.exists(mem_info):
        try:
            with open(mem_info, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        return int(parts[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass

    # Fallback to cached stats
    cached = getattr(Z_STATE, "cached_stats", {})
    if cached and "mem" in cached and cached["mem"].get("total_gb"):
        return int(cached["mem"]["total_gb"] * (1024**3))

    return 32 * 1024 * 1024 * 1024  # Standard default 32GB


def calculate_vm_budget(total_ram_bytes: int, running_vms: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Evaluates the Dynamic Elastic Headroom Reserve Formula:
    Host Reserve = max(2.0 GB, 0.10 * Total RAM GB)
    Safe Max VM Allocatable RAM = Total RAM GB - Host Reserve
    Remaining Safe Headroom = max(0, Safe Max VM Allocatable RAM - Allocated VM RAM)
    """
    total_ram_gb = total_ram_bytes / (1024**3)
    host_reserve_gb = max(2.0, round(0.10 * total_ram_gb, 2))
    safe_max_vm_ram_gb = max(0.0, round(total_ram_gb - host_reserve_gb, 2))

    # Allocated RAM in currently running VMs
    allocated_vm_ram_gb = 0.0
    for vm in running_vms:
        if vm.get("state") in ("running", "paused"):
            allocated_vm_ram_gb += float(vm.get("ram_gb", 0.0))

    allocated_vm_ram_gb = round(allocated_vm_ram_gb, 2)
    safe_headroom_gb = max(0.0, round(safe_max_vm_ram_gb - allocated_vm_ram_gb, 2))
    safe_slider_max_gb = int(safe_max_vm_ram_gb)

    return {
        "total_host_ram_gb": round(total_ram_gb, 2),
        "host_reserve_gb": host_reserve_gb,
        "host_reserve_pct": 10.0 if total_ram_gb >= 20.0 else round((host_reserve_gb / total_ram_gb) * 100, 1),
        "safe_max_vm_ram_gb": safe_max_vm_ram_gb,
        "safe_slider_max_gb": safe_slider_max_gb,
        "allocated_vm_ram_gb": allocated_vm_ram_gb,
        "safe_headroom_gb": safe_headroom_gb,
        "override_max_ram_gb": max(1.0, round(total_ram_gb - 1.0, 2)),
    }


def calculate_cpu_capacity(host_threads: int, running_vms: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Evaluates CPU thread allocation and overcommit ratio:
    R_cpu = (Allocated vCPUs) / (Host Threads)
    """
    allocated_vcpus = sum(int(vm.get("vcpus", 1)) for vm in running_vms if vm.get("state") in ("running", "paused"))
    ratio = round(allocated_vcpus / max(1, host_threads), 2)

    if ratio <= 1.0:
        status = "nominal"
        badge = "1:1 Physical Mapping"
    elif ratio <= 2.0:
        status = "moderate_overcommit"
        badge = f"Overcommit: {ratio}x"
    else:
        status = "heavy_overcommit"
        badge = f"Heavy Overcommit: {ratio}x"

    return {
        "host_threads": host_threads,
        "allocated_vcpus": allocated_vcpus,
        "overcommit_ratio": ratio,
        "status": status,
        "badge": badge,
        "recommended_max_vcpus": host_threads,
        "override_max_vcpus": min(64, host_threads * 4),
    }


def get_kvm_status() -> dict[str, Any]:
    """Inspects /dev/kvm presence, host kernel modules, and CPU virtualization flags with multi-tier diagnosis."""
    # Auto-link host KVM and vhost-net nodes if present
    for node, host_node in [("/dev/kvm", "/host/dev/kvm"), ("/dev/vhost-net", "/host/dev/vhost-net")]:
        if not os.path.exists(node) and os.path.exists(host_node):
            try:
                os.symlink(host_node, node)
            except OSError:
                pass

    kvm_candidates = ["/dev/kvm", "/host/dev/kvm"]
    kvm_present = any(os.path.exists(p) for p in kvm_candidates)

    found_node = None
    kvm_rw = False
    cgroup_restricted = False
    probe_error = None
    kvm_api_version = None

    for p in kvm_candidates:
        if os.path.exists(p):
            found_node = p
            try:
                fd = os.open(p, os.O_RDWR)
                kvm_rw = True
                try:
                    import fcntl

                    kvm_api_version = fcntl.ioctl(fd, vm_store.KVM_GET_API_VERSION, 0)
                except Exception:
                    kvm_api_version = 12
                finally:
                    os.close(fd)
                if p == "/host/dev/kvm" and not os.path.exists("/dev/kvm"):
                    try:
                        os.symlink(p, "/dev/kvm")
                    except OSError:
                        pass
                break
            except PermissionError as pe:
                if pe.errno == 1:
                    cgroup_restricted = True
                probe_error = f"PermissionError: errno={pe.errno} ({os.strerror(pe.errno or 0)})"
            except OSError as oe:
                probe_error = f"OSError: {oe}"

    vmx = False
    svm = False
    for cpu_path in [os.path.join(HOST_PROC, "cpuinfo"), "/host/proc/cpuinfo", "/proc/cpuinfo"]:
        if os.path.exists(cpu_path):
            try:
                with open(cpu_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    vmx = "vmx" in content
                    svm = "svm" in content
                break
            except OSError:
                pass

    hardware_virt = vmx or svm

    kvm_mod = False
    vendor_mod = False
    for mod_path in [os.path.join(HOST_PROC, "modules"), "/host/proc/modules", "/proc/modules"]:
        if os.path.exists(mod_path):
            try:
                with open(mod_path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                    kvm_mod = "kvm " in content
                    vendor_mod = ("kvm_intel " in content) or ("kvm_amd " in content)
                break
            except OSError:
                pass

    host_kvm_ready = hardware_virt and (kvm_mod or kvm_present)

    if kvm_present and kvm_rw:
        state = "active"
        substate = "active"
        badge = "KVM Accelerated: Active (" + ("Intel VT-x" if vmx else ("AMD-V" if svm else "Hardware Virt")) + ")"
        remediation = None
    elif hardware_virt:
        state = "restricted"
        if cgroup_restricted or (found_node and not kvm_rw):
            substate = "container_restricted"
            badge = "KVM: Host Ready (Docker cgroup restricted)"
            remediation = (
                "Hardware virtualization is active on the host, but the Docker container cgroup "
                "blocks access to /dev/kvm. Add '--device /dev/kvm' to Extra Parameters in your "
                "Unraid container template, or add devices: ['/dev/kvm:/dev/kvm'] and "
                "device_cgroup_rules: ['c 10:232 rwm'] to docker-compose.yml."
            )
        elif not vendor_mod and not kvm_mod:
            substate = "module_missing"
            badge = "KVM Kernel Module Missing"
            remediation = "Run 'modprobe kvm_intel' (or 'modprobe kvm_amd') on the host to load the KVM kernel module."
        else:
            substate = "restricted"
            badge = "KVM Emulation: Device restricted or module missing"
            remediation = "Ensure /dev/kvm exists on the host and has read/write permissions."
    else:
        state = "disabled"
        substate = "bios_disabled"
        badge = "Hardware Virtualization Disabled in BIOS"
        remediation = (
            "Reboot your server and enable Intel Virtualization Technology (VT-x) or AMD SVM in the BIOS/UEFI settings."
        )

    return {
        "device_present": kvm_present,
        "device_writable": kvm_rw,
        "kvm_rw": kvm_rw,
        "device_node": found_node,
        "intel_vtx": vmx,
        "amd_v": svm,
        "hardware_virt": hardware_virt,
        "module_loaded": kvm_mod and vendor_mod,
        "host_kvm_ready": host_kvm_ready,
        "cgroup_restricted": cgroup_restricted,
        "probe_error": probe_error,
        "state": state,
        "substate": substate,
        "badge": badge,
        "remediation": remediation,
        "kvm_api_version": kvm_api_version,
        "vtpm_available": _swtpm_binary() is not None,
        # The core image has no QEMU (OPS-11)
        "qemu_available": bool(shutil.which("qemu-system-x86_64") or os.path.exists("/usr/bin/qemu-system-x86_64")),
        "image_variant": _image_variant(),
    }


def _image_variant() -> str:
    from backend.config import IMAGE_VARIANT

    return IMAGE_VARIANT


def _get_target_iso_dir() -> str:
    """Returns the primary writable directory for storing ISO images."""
    candidates = []
    if VM_ISO_DIR and VM_ISO_DIR not in candidates:
        candidates.append(VM_ISO_DIR)
    for d in [
        "/mnt/user/isos",
        "/mnt/storage/isos",
        os.path.join(POOL_PATH, "isos"),
        os.path.join(DATA_DIR, "isos"),
    ]:
        if d not in candidates:
            candidates.append(d)
    for d in candidates:
        try:
            if not os.path.exists(d):
                os.makedirs(d, exist_ok=True)
            if os.access(d, os.W_OK):
                return d
        except OSError:
            pass
    fallback = os.path.join(DATA_DIR, "isos")
    os.makedirs(fallback, exist_ok=True)
    return fallback


def scan_isos() -> list[dict[str, Any]]:
    """Discovers bootable ISO and raw disk images in storage shares."""
    iso_dirs = []
    if VM_ISO_DIR and VM_ISO_DIR not in iso_dirs:
        iso_dirs.append(VM_ISO_DIR)
    for d in [
        "/mnt/user/isos",
        "/mnt/user/system/isos",
        "/mnt/storage/isos",
        os.path.join(POOL_PATH, "isos"),
        os.path.join(DATA_DIR, "isos"),
    ]:
        if d not in iso_dirs:
            iso_dirs.append(d)
    discovered = []
    seen = set()

    for d in iso_dirs:
        if os.path.isdir(d):
            try:
                for root, _, files in os.walk(d):
                    for f in files:
                        if f.lower().endswith((".iso", ".img")):
                            p = os.path.join(root, f)
                            if p not in seen:
                                seen.add(p)
                                try:
                                    stat = os.stat(p)
                                    size_gb = round(stat.st_size / (1024**3), 2)
                                    discovered.append(
                                        {
                                            "name": f,
                                            "path": p,
                                            "size_bytes": stat.st_size,
                                            "size_formatted": f"{size_gb} GB",
                                            "mtime": stat.st_mtime,
                                        }
                                    )
                                except OSError:
                                    pass
            except OSError:
                pass

    return sorted(discovered, key=lambda x: x["name"].lower())


def scan_bridges() -> list[str]:
    """Inspects Linux kernel network bridges for virtual machine attachment."""
    net_dirs = ["/host/sys/class/net", "/sys/class/net"]
    found = []
    for nd in net_dirs:
        if os.path.isdir(nd):
            try:
                for iface in os.listdir(nd):
                    if os.path.isdir(os.path.join(nd, iface, "bridge")) or iface.startswith(("br", "virbr")):
                        found.append(iface)
            except OSError:
                pass
    return sorted(list(set(found or ["br0", "virbr0"])))


def scan_host_usb_devices() -> list[dict[str, Any]]:
    """
    Discovers physical USB devices connected to the host via sysfs (/host/sys/bus/usb/devices or /sys/bus/usb/devices).
    Returns list of devices sorted with physical peripherals first and root hubs last.
    """
    sys_paths = ["/host/sys/bus/usb/devices", "/sys/bus/usb/devices"]
    usb_dir = next((p for p in sys_paths if os.path.isdir(p)), None)
    if not usb_dir:
        return []

    devices = []
    seen = set()

    try:
        entries = sorted(os.listdir(usb_dir))
    except OSError:
        return []

    for entry in entries:
        # Skip sub-interface descriptors (e.g. 1-0:1.0, 3-5:1.0)
        if ":" in entry:
            continue
        dev_path = os.path.join(usb_dir, entry)
        id_vendor_f = os.path.join(dev_path, "idVendor")
        id_product_f = os.path.join(dev_path, "idProduct")
        if not (os.path.exists(id_vendor_f) and os.path.exists(id_product_f)):
            continue

        try:
            with open(id_vendor_f, encoding="utf-8", errors="replace") as f:
                vid = f.read().strip().lower()
            with open(id_product_f, encoding="utf-8", errors="replace") as f:
                pid = f.read().strip().lower()
        except OSError:
            continue

        def _read_prop(prop_name: str) -> str:
            p = os.path.join(dev_path, prop_name)  # noqa: B023
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        return f.read().strip()
                except OSError:
                    pass
            return ""

        mfr = _read_prop("manufacturer")
        prod = _read_prop("product")
        bus = _read_prop("busnum")
        dev = _read_prop("devnum")
        serial = _read_prop("serial")

        is_root_hub = vid == "1d6b"
        composite_key = f"{vid}:{pid}:{bus}:{dev}"
        if composite_key in seen:
            continue
        seen.add(composite_key)

        display_name = prod or (f"Root Hub ({bus})" if is_root_hub else f"USB Device ({vid}:{pid})")
        mfr_name = mfr or ("Linux Foundation" if is_root_hub else "Generic")

        devices.append(
            {
                "vendor_id": vid,
                "product_id": pid,
                "vendor_hex": f"0x{vid}",
                "product_hex": f"0x{pid}",
                "manufacturer": mfr_name,
                "product": display_name,
                "description": f"{mfr_name} {display_name}".strip(),
                "bus": bus,
                "dev": dev,
                "serial": serial,
                "is_root_hub": is_root_hub,
                "sysfs_path": entry,
            }
        )

    # Sort: physical devices first, then root hubs
    return sorted(devices, key=lambda x: (x["is_root_hub"], x["description"].lower()))


def _find_ovmf_firmware() -> tuple[str | None, str | None]:
    """Discovers OVMF/EDK2 UEFI firmware binary and NVRAM variable template."""
    code_candidates = [
        "/usr/share/OVMF/OVMF_CODE_4M.ms.fd",
        "/usr/share/OVMF/OVMF_CODE_4M.fd",
        "/usr/share/qemu/ovmf-x64/OVMF_CODE-pure-efi.fd",
        "/usr/share/qemu/ovmf-x64/OVMF_CODE-pure-efi-tpm.fd",
        "/usr/share/qemu/edk2-x86_64-code.fd",
        "/usr/share/OVMF/OVMF_CODE.fd",
        "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd",
        "/usr/share/edk2/ovmf/OVMF_CODE.fd",
        "/usr/share/ovmf/OVMF.fd",
        "/usr/share/qemu/OVMF.fd",
    ]
    vars_candidates = [
        "/usr/share/OVMF/OVMF_VARS_4M.ms.fd",
        "/usr/share/OVMF/OVMF_VARS_4M.fd",
        "/usr/share/qemu/ovmf-x64/OVMF_VARS-pure-efi.fd",
        "/usr/share/qemu/ovmf-x64/OVMF_VARS-pure-efi-tpm.fd",
        "/usr/share/qemu/edk2-x86_64-vars.fd",
        "/usr/share/OVMF/OVMF_VARS.fd",
        "/usr/share/edk2-ovmf/x64/OVMF_VARS.fd",
        "/usr/share/edk2/ovmf/OVMF_VARS.fd",
    ]
    code_path = next((p for p in code_candidates if os.path.exists(p)), None)
    vars_path = next((p for p in vars_candidates if os.path.exists(p)), None)
    return code_path, vars_path


def _can_use_kvm() -> bool:
    """Verifies KVM hardware acceleration availability by testing character device read/write open."""
    for kvm_path in ("/dev/kvm", "/host/dev/kvm"):
        if os.path.exists(kvm_path):
            try:
                fd = os.open(kvm_path, os.O_RDWR)
                os.close(fd)
                if kvm_path == "/host/dev/kvm" and not os.path.exists("/dev/kvm"):
                    try:
                        os.symlink(kvm_path, "/dev/kvm")
                    except OSError:
                        pass
                return True
            except (PermissionError, OSError):
                continue
    return False


_PCI_SLOT_RE = re.compile(r"^(?:[0-9a-fA-F]{4}:)?([0-9a-fA-F]{2}:[0-9a-fA-F]{2}\.[0-7])$")


_PCI_SYSFS_BASES = ("/sys/bus/pci/devices", "/host/sys/bus/pci/devices")


_VFIO_NODES = ("/dev/vfio/vfio", "/host/dev/vfio/vfio")


def _normalize_pci_slot(raw: Any) -> str | None:
    """'0000:01:00.0' or '01:00.0' -> '01:00.0'; None for anything else."""
    m = _PCI_SLOT_RE.match(str(raw or "").strip())
    return m.group(1).lower() if m else None


def _sanitize_pci_list(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        slot = _normalize_pci_slot(item.get("slot"))
        if not slot or slot in seen:
            continue
        seen.add(slot)
        out.append({"slot": slot, "name": str(item.get("name") or "")[:120]})
    return out


def _pci_device_driver(slot: str) -> str:
    """Kernel driver currently bound to a PCI device ('' when none or unknown)."""
    norm = _normalize_pci_slot(slot)
    if not norm:
        return ""
    full = f"0000:{norm}"
    for base in _PCI_SYSFS_BASES:
        dev = os.path.join(base, full)
        link = os.path.join(dev, "driver")
        if os.path.islink(link):
            return os.path.basename(os.readlink(link))
        if os.path.exists(dev):
            return ""
    return ""


def _vfio_available() -> bool:
    return any(os.path.exists(p) for p in _VFIO_NODES)


def _ensure_vfio_dev() -> bool:
    """Makes /dev/vfio usable inside the container, linking the host node like /dev/kvm."""
    if os.path.exists("/dev/vfio/vfio"):
        return True
    if os.path.isdir("/host/dev/vfio") and not os.path.lexists("/dev/vfio"):
        try:
            os.symlink("/host/dev/vfio", "/dev/vfio")
        except OSError:
            return False
    return os.path.exists("/dev/vfio/vfio")


def _pci_passthrough_problem(target_vm: dict[str, Any]) -> str | None:
    """Why the VM's PCI passthrough cannot work right now, or None when it can.

    QEMU only takes devices that the host has handed to vfio-pci; anything else
    (a GPU on i915/nvidia, a SATA controller on ahci...) is still in host use.
    """
    devices = _sanitize_pci_list(target_vm.get("pci_passthrough"))
    if not devices:
        return None
    for dev in devices:
        driver = _pci_device_driver(dev["slot"])
        if driver != "vfio-pci":
            current = f"the '{driver}' driver" if driver else "no driver"
            return f"PCI device {dev['slot']} is on {current}. Bind it to vfio-pci on the host before starting this VM."
    if not _ensure_vfio_dev():
        return "/dev/vfio is not available in the container. Pass it through (e.g. --device /dev/vfio) to use PCI passthrough."
    return None


def _swtpm_binary() -> str | None:
    """Path to the swtpm TPM emulator, or None when it is not installed."""
    found = shutil.which("swtpm")
    if found:
        return found
    return "/usr/bin/swtpm" if os.path.exists("/usr/bin/swtpm") else None


def _get_host_ip() -> str:
    from backend.state import Z_STATE

    return getattr(Z_STATE, "discovered_host_ip", None) or os.environ.get("HOST_IP") or "127.0.0.1"
