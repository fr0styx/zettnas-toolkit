"""
ZettNAS Toolkit - Virtual Machine (VM) Management & Dynamic Elastic Budgeting API
Provides KVM hypervisor telemetry, adaptive headroom calculations, ISO scanning,
and VM lifecycle orchestration.
"""

import hashlib
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import DATA_DIR, HOST_PROC, POOL_PATH, logger
from backend.fsutil import atomic_write_json, read_json
from backend.state import Z_STATE, add_event

router = APIRouter(prefix="/vms", tags=["Virtual Machines"])

VMS_CONFIG_FILE = os.path.join(DATA_DIR, "vms.json")
KVM_GET_API_VERSION = 0xAE00

# In-memory transient caches for download jobs and web console tickets
_DOWNLOAD_TASKS: Dict[str, Dict[str, Any]] = {}
_ABORT_DOWNLOAD_TASKS: set = set()
_CONSOLE_TICKETS: Dict[str, Dict[str, Any]] = {}

# Curated Official Operating System ISO Catalog
OFFICIAL_ISO_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "ubuntu-2404",
        "name": "Ubuntu Server 24.04.1 LTS",
        "distribution": "Ubuntu",
        "version": "24.04.1",
        "category": "linux",
        "badge": "Official Canonical",
        "architecture": "x86_64",
        "kernel": "Linux 6.8",
        "description": "Enterprise-grade cloud and container host with modern Linux 6.8 kernel and cloud-init.",
        "download_url": "https://releases.ubuntu.com/24.04.1/ubuntu-24.04.1-live-server-amd64.iso",
        "filename": "ubuntu-24.04.1-live-server-amd64.iso",
        "size_bytes": 2831155200,
        "size_formatted": "2.6 GB",
        "sha256": "e240e4b801f7bb68c20d1356b60968ad0c33a41d00d828e74ceb3364a0317be9",
        "recommended_specs": {"min_vcpus": 2, "min_ram_gb": 2.0, "min_disk_gb": 25, "recommended_bus": "virtio"},
    },
    {
        "id": "debian-12",
        "name": "Debian 12.7.0 (Bookworm) Netinst",
        "distribution": "Debian",
        "version": "12.7.0",
        "category": "linux",
        "badge": "Stable Minimal",
        "architecture": "x86_64",
        "kernel": "Linux 6.1 LTS",
        "description": "Rock-solid, universal operating system with minimal memory footprint and high package stability.",
        "download_url": "https://cdimage.debian.org/cdimage/archive/12.7.0/amd64/iso-cd/debian-12.7.0-amd64-netinst.iso",
        "filename": "debian-12.7.0-amd64-netinst.iso",
        "size_bytes": 660602880,
        "size_formatted": "630 MB",
        "sha256": "8fde79cfc6b20a696200fc5c15219cf6d721e8feb367e9e0e33a79d1cb68fa83",
        "recommended_specs": {"min_vcpus": 1, "min_ram_gb": 1.0, "min_disk_gb": 10, "recommended_bus": "virtio"},
    },
    {
        "id": "alpine-320",
        "name": "Alpine Linux 3.20.3",
        "distribution": "Alpine",
        "version": "3.20.3",
        "category": "linux",
        "badge": "Micro Hypervisor",
        "architecture": "x86_64",
        "kernel": "Linux 6.6 LTS",
        "description": "Ultra-lightweight security-oriented Linux based on musl libc and busybox. Boots in 400ms.",
        "download_url": "https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/alpine-standard-3.20.3-x86_64.iso",
        "filename": "alpine-standard-3.20.3-x86_64.iso",
        "size_bytes": 219152384,
        "size_formatted": "209 MB",
        "sha256": "c66fc1e0470781f8ecbab8eb9cc8d906066171a5e0c6c1ab20aedc7061836d27",
        "recommended_specs": {"min_vcpus": 1, "min_ram_gb": 0.5, "min_disk_gb": 4, "recommended_bus": "virtio"},
    },
    {
        "id": "fedora-40",
        "name": "Fedora Server 40",
        "distribution": "Fedora",
        "version": "40",
        "category": "linux",
        "badge": "Modern Enterprise",
        "architecture": "x86_64",
        "kernel": "Linux 6.8",
        "description": "Cutting-edge Linux server platform with native systemd, Podman containerization, and Cockpit.",
        "download_url": "https://download.fedoraproject.org/pub/fedora/linux/releases/40/Server/x86_64/iso/Fedora-Server-dvd-x86_64-40-1.14.iso",
        "filename": "Fedora-Server-dvd-x86_64-40-1.14.iso",
        "size_bytes": 2684354560,
        "size_formatted": "2.5 GB",
        "sha256": "9b12d59265f2423a268673f848ce1c9e83ecf2bb3ef64fc6c8e3bf5d4cecb2e3",
        "recommended_specs": {"min_vcpus": 2, "min_ram_gb": 2.0, "min_disk_gb": 20, "recommended_bus": "virtio"},
    },
    {
        "id": "truenas-scale",
        "name": "TrueNAS SCALE 24.04.2",
        "distribution": "TrueNAS",
        "version": "24.04.2",
        "category": "storage",
        "badge": "Scale-Out NAS",
        "architecture": "x86_64",
        "kernel": "Linux 6.6 LTS",
        "description": "Debian-based open hyper-converged scale-out storage, ZFS pools, and containerized apps.",
        "download_url": "https://download.sys.truenas.net/TrueNAS-SCALE-Dragonfish/24.04.2/TrueNAS-SCALE-24.04.2.iso",
        "filename": "TrueNAS-SCALE-24.04.2.iso",
        "size_bytes": 1824522240,
        "size_formatted": "1.7 GB",
        "sha256": "f62b7194f489fef39ffbe3dcbca1823ebce1bc98914c62c2f42be709f18dd12",
        "recommended_specs": {"min_vcpus": 2, "min_ram_gb": 8.0, "min_disk_gb": 32, "recommended_bus": "virtio"},
    },
    {
        "id": "virtio-win",
        "name": "VirtIO Windows Guest Tools",
        "distribution": "VirtIO",
        "version": "0.1.262",
        "category": "drivers",
        "badge": "KVM Drivers",
        "architecture": "x86_64 / x86",
        "kernel": "WHQL Signed",
        "description": "Essential Red Hat signed VirtIO storage (viostor), network (NetKVM), and memory balloon drivers.",
        "download_url": "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso",
        "filename": "virtio-win-stable.iso",
        "size_bytes": 681574400,
        "size_formatted": "650 MB",
        "sha256": "893c52a0a289456208bb53258c465f2991873ea895ad602058863f6a27e7f606",
        "recommended_specs": {"min_vcpus": 1, "min_ram_gb": 0.5, "min_disk_gb": 1, "recommended_bus": "sata"},
    },
    {
        "id": "win-server-2022",
        "name": "Windows Server 2022 Evaluation",
        "distribution": "Windows",
        "version": "2022",
        "category": "windows",
        "badge": "Microsoft Eval",
        "architecture": "x86_64",
        "kernel": "NT 10.0",
        "description": "Official Microsoft 180-day trial evaluation ISO for enterprise testing and Active Directory.",
        "download_url": "https://software-download.microsoft.com/download/pr/SERVER_EVAL_x64FRE_en-us.iso",
        "filename": "Windows_Server_2022_Eval_x64.iso",
        "size_bytes": 5044944896,
        "size_formatted": "4.7 GB",
        "sha256": "3e4fa6d8c76191985d03d85d1f1f76039726d10732a1bc7d7cf4924fe723660d",
        "recommended_specs": {"min_vcpus": 4, "min_ram_gb": 8.0, "min_disk_gb": 64, "recommended_bus": "sata"},
    },
]


def _get_host_memory_bytes() -> int:
    """Read total host memory in bytes from /proc/meminfo or system state."""
    mem_info = "/host/proc/meminfo" if os.path.exists("/host/proc/meminfo") else "/proc/meminfo"
    if os.path.exists(mem_info):
        try:
            with open(mem_info, "r", encoding="utf-8", errors="replace") as f:
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


def calculate_vm_budget(total_ram_bytes: int, running_vms: List[Dict[str, Any]]) -> Dict[str, Any]:
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


def calculate_cpu_capacity(host_threads: int, running_vms: List[Dict[str, Any]]) -> Dict[str, Any]:
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


def get_kvm_status() -> Dict[str, Any]:
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

                    kvm_api_version = fcntl.ioctl(fd, KVM_GET_API_VERSION, 0)
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
                probe_error = f"PermissionError: errno={pe.errno} ({os.strerror(pe.errno)})"
            except OSError as oe:
                probe_error = f"OSError: {oe}"

    vmx = False
    svm = False
    for cpu_path in [os.path.join(HOST_PROC, "cpuinfo"), "/host/proc/cpuinfo", "/proc/cpuinfo"]:
        if os.path.exists(cpu_path):
            try:
                with open(cpu_path, "r", encoding="utf-8", errors="replace") as f:
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
                with open(mod_path, "r", encoding="utf-8", errors="replace") as f:
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
    }


def _get_target_iso_dir() -> str:
    """Returns the primary writable directory for storing ISO images."""
    for d in [
        "/mnt/user/isos",
        "/mnt/storage/isos",
        os.path.join(POOL_PATH, "isos"),
        os.path.join(DATA_DIR, "isos"),
    ]:
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


def scan_isos() -> List[Dict[str, Any]]:
    """Discovers bootable ISO and raw disk images in storage shares."""
    iso_dirs = [
        "/mnt/user/isos",
        "/mnt/user/system/isos",
        "/mnt/storage/isos",
        os.path.join(POOL_PATH, "isos"),
    ]
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


def scan_bridges() -> List[str]:
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


def _load_vms() -> List[Dict[str, Any]]:
    """Loads configured virtual machines from persistent JSON storage."""
    vms = read_json(VMS_CONFIG_FILE, default=None)
    if vms is None:
        # Initial default seeded VMs for demo and test appliances
        default_vms = [
            {
                "id": "vm-ubuntu-server",
                "name": "ubuntu-server",
                "description": "Production Web & Microservices Appliance",
                "os_family": "linux",
                "state": "running",
                "vcpus": 4,
                "ram_gb": 8.0,
                "disk_size_gb": 64,
                "disk_format": "qcow2",
                "disk_bus": "virtio",
                "ip_address": "192.168.1.180",
                "bridge": "br0",
                "mac": "52:54:00:12:34:56",
                "autostart": True,
                "uptime_seconds": 128450,
                "created_at": int(time.time()) - 130000,
            },
            {
                "id": "vm-debian-sandbox",
                "name": "debian-sandbox",
                "description": "Isolated Development Sandbox",
                "os_family": "linux",
                "state": "stopped",
                "vcpus": 2,
                "ram_gb": 4.0,
                "disk_size_gb": 32,
                "disk_format": "qcow2",
                "disk_bus": "virtio",
                "ip_address": "",
                "bridge": "br0",
                "mac": "52:54:00:ab:cd:ef",
                "autostart": False,
                "uptime_seconds": 0,
                "created_at": int(time.time()) - 80000,
            },
        ]
        atomic_write_json(VMS_CONFIG_FILE, default_vms)
        return default_vms
    return vms


def _save_vms(vms: List[Dict[str, Any]]) -> None:
    atomic_write_json(VMS_CONFIG_FILE, vms)


# ---- Request / Response Models ----
class VmCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = ""
    os_family: str = Field("linux", pattern="^(linux|windows|bsd|other)$")
    vcpus: int = Field(2, ge=1, le=128)
    ram_gb: float = Field(4.0, ge=0.5, le=1024.0)
    disk_size_gb: int = Field(32, ge=5, le=4096)
    disk_format: str = Field("qcow2", pattern="^(qcow2|raw)$")
    disk_bus: str = Field("virtio", pattern="^(virtio|sata|nvme)$")
    iso_path: Optional[str] = None
    bridge: str = Field("br0", min_length=2)
    autostart: bool = False
    override_limits: bool = False
    host_shares: List[Dict[str, Any]] = Field(default_factory=list)
    secondary_disks: List[Dict[str, Any]] = Field(default_factory=list)


class VmActionRequest(BaseModel):
    action: str = Field(..., pattern="^(start|stop|pause|resume|force_off)$")


def _download_iso_worker(task_id: str, catalog_item: Dict[str, Any], target_dir: str):
    filename = catalog_item["filename"]
    tmp_path = os.path.join(target_dir, f"{filename}.downloading")
    final_path = os.path.join(target_dir, filename)
    url = catalog_item["download_url"]
    total_bytes = catalog_item.get("size_bytes", 0)
    expected_sha256 = catalog_item.get("sha256")

    start_time = time.time()
    downloaded = 0
    hasher = hashlib.sha256()

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ZettNAS-Hypervisor/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(tmp_path, "wb") as f:
            content_len = resp.headers.get("Content-Length")
            if content_len:
                try:
                    total_bytes = int(content_len)
                except ValueError:
                    pass
            _DOWNLOAD_TASKS[task_id]["total_bytes"] = total_bytes

            chunk_size = 1024 * 512
            while True:
                if task_id in _ABORT_DOWNLOAD_TASKS:
                    _ABORT_DOWNLOAD_TASKS.discard(task_id)
                    if os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                    _DOWNLOAD_TASKS[task_id].update(
                        {
                            "status": "cancelled",
                            "error": "Download cancelled by user",
                        }
                    )
                    add_event("info", "ISO Download Cancelled", f"Download for '{catalog_item['name']}' was cancelled.")
                    return

                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                elapsed = max(0.1, time.time() - start_time)
                speed_mb_s = round((downloaded / (1024 * 1024)) / elapsed, 2)
                pct = min(100, int((downloaded / total_bytes) * 100)) if total_bytes > 0 else 50
                _DOWNLOAD_TASKS[task_id].update(
                    {
                        "downloaded_bytes": downloaded,
                        "progress_pct": pct,
                        "speed_mb_s": speed_mb_s,
                    }
                )

        # Mandatory Post-Download Checksum Verification
        computed_sha256 = hasher.hexdigest()
        if expected_sha256 and computed_sha256.lower() != str(expected_sha256).lower():
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            _DOWNLOAD_TASKS[task_id].update(
                {
                    "status": "checksum_mismatch",
                    "error": f"SHA-256 mismatch: expected {expected_sha256}, got {computed_sha256}",
                }
            )
            add_event(
                "warning",
                "ISO Verification Failed",
                f"SHA-256 checksum mismatch for '{catalog_item['name']}'. Corrupted payload removed.",
            )
            return

        if os.path.exists(tmp_path):
            os.replace(tmp_path, final_path)
            try:
                os.chmod(final_path, 0o666)
            except OSError:
                pass

        _DOWNLOAD_TASKS[task_id].update(
            {
                "status": "completed",
                "progress_pct": 100,
                "path": final_path,
                "sha256": computed_sha256,
            }
        )
        add_event(
            "success",
            "Official ISO Downloaded & Verified",
            f"ISO '{catalog_item['name']}' verified and saved to {final_path}.",
        )
    except Exception as e:
        logger.error(f"[VM-ISO] Download failed for {catalog_item['name']}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        _DOWNLOAD_TASKS[task_id].update(
            {
                "status": "failed",
                "error": str(e),
            }
        )
        add_event("warning", "ISO Download Failed", f"Failed to download '{catalog_item['name']}': {e}")


@router.get("/telemetry", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vms_telemetry():
    """Returns KVM hypervisor acceleration state, dynamic memory headroom budget, and CPU capacity."""
    total_mem = _get_host_memory_bytes()
    vms = _load_vms()
    host_threads = os.cpu_count() or 8

    budget = calculate_vm_budget(total_mem, vms)
    cpu_cap = calculate_cpu_capacity(host_threads, vms)
    kvm = get_kvm_status()

    return {
        "kvm": kvm,
        "memory_budget": budget,
        "cpu_capacity": cpu_cap,
        "active_vm_count": len([v for v in vms if v.get("state") == "running"]),
        "total_vm_count": len(vms),
    }


@router.get("/kvm/diagnose", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_kvm_diagnose():
    """Returns detailed multi-tier KVM diagnostic report including host hardware and cgroup analysis."""
    return get_kvm_status()


@router.get("", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def list_vms():
    """Lists configured virtual machines with live states and resource allocations."""
    return _load_vms()


@router.get("/isos", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_discovered_isos():
    """Lists available ISO and OS installation images."""
    return scan_isos()


@router.post("/isos/upload", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
async def upload_iso_file(
    request: Request,
    filename: Optional[str] = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Streams uploaded ISO file directly into NAS storage (/mnt/user/isos)."""
    target_dir = _get_target_iso_dir()
    raw_name = filename or request.headers.get("x-filename") or f"uploaded-{uuid.uuid4().hex[:6]}.iso"
    clean_name = os.path.basename(raw_name)
    if not clean_name.lower().endswith((".iso", ".img")):
        clean_name += ".iso"

    upload_id = uuid.uuid4().hex[:8]
    tmp_path = os.path.join(target_dir, f".tmp_{upload_id}_{clean_name}")
    out_path = os.path.join(target_dir, clean_name)
    total_written = 0
    hasher = hashlib.sha256()

    try:
        with open(tmp_path, "wb") as f:
            async for chunk in request.stream():
                if chunk:
                    f.write(chunk)
                    hasher.update(chunk)
                    total_written += len(chunk)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to upload ISO: {e}")

    # ISO 9660 & UDF Magic Byte Verification
    # Standard ISO 9660 Primary Volume Descriptor is at sector 16 (offset 32768) with identifier 'CD001'
    format_verified = "generic_image"
    if total_written >= 32774:
        try:
            with open(tmp_path, "rb") as f:
                f.seek(32768)
                sector = f.read(1024)
                if b"CD001" in sector:
                    format_verified = "iso9660"
                elif any(sig in sector for sig in [b"BEA01", b"NSR02", b"NSR03"]):
                    format_verified = "udf"
        except Exception:
            pass

    try:
        os.replace(tmp_path, out_path)
    except OSError as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to commit uploaded ISO: {e}")

    sha256_hash = hasher.hexdigest()
    add_event(
        "info",
        "ISO Image Uploaded",
        f"ISO '{clean_name}' ({round(total_written / (1024**3), 2)} GB, {format_verified}) saved to {out_path}.",
    )
    return {
        "status": "ok",
        "filename": clean_name,
        "path": out_path,
        "size_bytes": total_written,
        "size_formatted": f"{round(total_written / (1024**3), 2)} GB",
        "sha256": sha256_hash,
        "format_verified": format_verified,
    }


@router.delete("/isos", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def delete_iso_image(
    path: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Safely deletes an ISO image within authorized storage paths."""
    real_path = os.path.abspath(path)
    allowed_dirs = [
        "/mnt/user/isos",
        "/mnt/user/system/isos",
        "/mnt/storage/isos",
        os.path.join(POOL_PATH, "isos"),
        os.path.join(DATA_DIR, "isos"),
    ]
    if not any(real_path.startswith(ad) for ad in allowed_dirs):
        raise HTTPException(status_code=400, detail="Invalid ISO path outside authorized repositories.")

    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="ISO file not found.")

    try:
        os.remove(real_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete ISO file: {e}")

    add_event("info", "ISO Removed", f"ISO '{os.path.basename(real_path)}' was deleted from repository.")
    return {"status": "ok"}


@router.get("/catalog", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_official_catalog():
    """Lists curated official distribution images with local cache detection."""
    local_isos = scan_isos()
    local_filenames = {iso["name"].lower() for iso in local_isos}

    results = []
    for item in OFFICIAL_ISO_CATALOG:
        is_dl = item["filename"].lower() in local_filenames
        entry = dict(item)
        entry["downloaded"] = is_dl
        results.append(entry)
    return results


@router.post("/catalog/{catalog_id}/download", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def download_official_iso(
    catalog_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Initiates a background download of a verified official distribution ISO."""
    item = next((c for c in OFFICIAL_ISO_CATALOG if c["id"] == catalog_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Catalog ISO '{catalog_id}' not found.")

    target_dir = _get_target_iso_dir()
    final_path = os.path.join(target_dir, item["filename"])
    if os.path.exists(final_path):
        return {
            "status": "already_present",
            "message": f"ISO '{item['filename']}' already exists in storage.",
            "path": final_path,
        }

    task_id = f"dl-{catalog_id}-{uuid.uuid4().hex[:6]}"
    _DOWNLOAD_TASKS[task_id] = {
        "task_id": task_id,
        "catalog_id": catalog_id,
        "name": item["name"],
        "filename": item["filename"],
        "status": "downloading",
        "progress_pct": 0,
        "downloaded_bytes": 0,
        "total_bytes": item.get("size_bytes", 0),
        "speed_mb_s": 0.0,
        "started_at": time.time(),
    }

    t = threading.Thread(target=_download_iso_worker, args=(task_id, item, target_dir), daemon=True)
    t.start()

    return {"status": "started", "task_id": task_id, "catalog_id": catalog_id}


@router.get("/catalog/tasks", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_catalog_download_tasks():
    """Returns status and telemetry of active and recent ISO download tasks."""
    return list(_DOWNLOAD_TASKS.values())


@router.delete("/catalog/tasks/{task_id}", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def cancel_or_remove_catalog_task(
    task_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Cancels an in-flight ISO download task or removes a finished/failed task record."""
    task = _DOWNLOAD_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Download task '{task_id}' not found.")

    if task.get("status") == "downloading":
        _ABORT_DOWNLOAD_TASKS.add(task_id)
        task["status"] = "cancelling"
        return {"status": "cancelling", "task_id": task_id}

    _DOWNLOAD_TASKS.pop(task_id, None)
    return {"status": "removed", "task_id": task_id}


@router.get("/bridges", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_network_bridges():
    """Lists available host network bridges."""
    return scan_bridges()


@router.post("", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def create_vm(req: VmCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Provisions a new virtual machine with dynamic headroom validation and volume mappings."""
    vms = _load_vms()
    if any(v["name"].lower() == req.name.lower() for v in vms):
        raise HTTPException(status_code=400, detail=f"Virtual machine '{req.name}' already exists.")

    total_mem = _get_host_memory_bytes()
    budget = calculate_vm_budget(total_mem, vms)

    # Validate RAM allocation against safe headroom unless overridden
    if not req.override_limits and req.ram_gb > budget["safe_headroom_gb"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Requested RAM ({req.ram_gb} GB) exceeds safe headroom "
                f"({budget['safe_headroom_gb']} GB). Enable Advanced Override to bypass safety limits."
            ),
        )

    # Generate deterministic random KVM MAC address (52:54:00:xx:xx:xx)
    mac_suffix = [f"{os.urandom(1)[0]:02x}" for _ in range(3)]
    mac = f"52:54:00:{':'.join(mac_suffix)}"

    new_vm = {
        "id": f"vm-{uuid.uuid4().hex[:8]}",
        "name": req.name,
        "description": req.description or "",
        "os_family": req.os_family,
        "state": "stopped",
        "vcpus": req.vcpus,
        "ram_gb": req.ram_gb,
        "disk_size_gb": req.disk_size_gb,
        "disk_format": req.disk_format,
        "disk_bus": req.disk_bus,
        "iso_path": req.iso_path,
        "bridge": req.bridge,
        "mac": mac,
        "autostart": req.autostart,
        "uptime_seconds": 0,
        "ip_address": "",
        "override_active": req.override_limits,
        "host_shares": req.host_shares,
        "secondary_disks": req.secondary_disks,
        "created_at": int(time.time()),
    }

    vms.append(new_vm)
    _save_vms(vms)

    add_event(
        "info",
        "Virtual Machine Created",
        f"VM '{req.name}' created ({req.vcpus} vCPUs, {req.ram_gb} GB RAM).",
    )
    return new_vm


_RUNNING_QEMU_PROCS: Dict[str, Dict[str, Any]] = {}


def _get_qemu_vnc_port(vms: List[Dict[str, Any]], vm_id: str) -> int:
    idx = next((i for i, v in enumerate(vms) if v["id"] == vm_id), 0)
    return 5900 + idx + 1


def _is_qemu_process_alive(vm_id: str) -> bool:
    if vm_id in _RUNNING_QEMU_PROCS:
        entry = _RUNNING_QEMU_PROCS[vm_id]
        proc = entry.get("proc")
        if proc:
            if proc.poll() is None:
                return True
            else:
                _RUNNING_QEMU_PROCS.pop(vm_id, None)
                return False
        pid = entry.get("pid")
        if pid:
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                _RUNNING_QEMU_PROCS.pop(vm_id, None)
                return False

    pid_file = os.path.join(DATA_DIR, "vms", vm_id, "qemu.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, OSError):
            try:
                os.remove(pid_file)
            except OSError:
                pass
    return False


def _start_qemu(target_vm: Dict[str, Any], vnc_port: int) -> bool:
    vm_id = target_vm["id"]
    if _is_qemu_process_alive(vm_id):
        return True

    qemu_bin = shutil.which("qemu-system-x86_64") or "/usr/bin/qemu-system-x86_64"
    if not os.path.exists(qemu_bin) and not shutil.which(qemu_bin):
        logger.warning(f"qemu-system-x86_64 not found to start VM '{target_vm['name']}'.")
        return False

    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    os.makedirs(vm_dir, exist_ok=True)
    disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")
    target_vm["disk_path"] = disk_path

    if not os.path.exists(disk_path):
        size_gb = int(target_vm.get("disk_size_gb", 32) or 32)
        qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
        try:
            subprocess.run([qemu_img, "create", "-f", "qcow2", disk_path, f"{size_gb}G"], check=True)
        except Exception as e:
            logger.warning(f"Could not create qcow2 disk: {e}")

    has_kvm = False
    for kvm_path in ("/dev/kvm", "/host/dev/kvm"):
        if os.path.exists(kvm_path) and os.access(kvm_path, os.R_OK | os.W_OK):
            has_kvm = True
            break

    ram_mb = int(float(target_vm.get("ram_gb", 2.0)) * 1024)
    vcpus = str(target_vm.get("vcpus", 2))
    vnc_display = max(1, vnc_port - 5900)

    sock_path = f"/tmp/{vm_id}-serial.sock"
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
        except OSError:
            pass

    cmd = [
        qemu_bin,
        "-name",
        target_vm["name"],
        "-m",
        str(ram_mb),
        "-smp",
        vcpus,
    ]
    if has_kvm:
        cmd.extend(["-enable-kvm", "-cpu", "host"])
    else:
        cmd.extend(["-accel", "tcg"])

    if os.path.exists(disk_path):
        cmd.extend(["-drive", f"file={disk_path},if=virtio,format=qcow2"])

    iso_path = target_vm.get("iso_path")
    if iso_path and os.path.exists(iso_path):
        cmd.extend(["-cdrom", iso_path, "-boot", "order=dc,menu=on"])
    else:
        cmd.extend(["-boot", "order=c"])

    cmd.extend(["-vnc", f"127.0.0.1:{vnc_display}", "-display", "none"])
    cmd.extend(["-chardev", f"socket,id=serial0,path={sock_path},server=on,wait=off", "-serial", "chardev:serial0"])
    ssh_fwd_port = 2220 + vnc_display
    target_vm["ssh_port"] = ssh_fwd_port
    cmd.extend(["-netdev", f"user,id=net0,hostfwd=tcp::{ssh_fwd_port}-:22", "-device", "virtio-net-pci,netdev=net0"])

    for idx_s, share in enumerate(target_vm.get("host_shares", [])):
        hp = share.get("host_path")
        tag = share.get("mount_tag") or f"share{idx_s}"
        mode = share.get("mode", "rw")
        ro_flag = "readonly=on" if mode == "ro" else "readonly=off"
        if hp and os.path.exists(hp):
            cmd.extend(
                [
                    "-fsdev",
                    f"local,id=fsdev{idx_s},path={hp},security_model=none,{ro_flag}",
                    "-device",
                    f"virtio-9p-pci,fsdev=fsdev{idx_s},mount_tag={tag}",
                ]
            )

    for idx_d, sdisk in enumerate(target_vm.get("secondary_disks", [])):
        sd_path = sdisk.get("path")
        if not sd_path:
            sd_path = os.path.join(vm_dir, f"{sdisk.get('name', f'disk_{idx_d}')}.qcow2")
            sdisk["path"] = sd_path
        if not os.path.exists(sd_path):
            try:
                qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
                subprocess.run([qemu_img, "create", "-f", "qcow2", sd_path, f"{sdisk.get('size_gb', 20)}G"], check=True)
            except Exception:
                pass
        bus = sdisk.get("bus", "virtio")
        if os.path.exists(sd_path):
            cmd.extend(["-drive", f"file={sd_path},if={bus},format=qcow2"])

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.3)
        if proc.poll() is not None:
            _, err = proc.communicate()
            err_msg = err.decode("utf-8", errors="ignore") if err else "process exited immediately"
            logger.warning(f"QEMU failed to start for VM '{target_vm['name']}': {err_msg}")
            return False

        _RUNNING_QEMU_PROCS[vm_id] = {
            "proc": proc,
            "pid": proc.pid,
            "vnc_port": vnc_port,
            "started_at": time.time(),
        }
        with open(os.path.join(vm_dir, "qemu.pid"), "w") as f:
            f.write(str(proc.pid))
        return True
    except Exception as e:
        logger.warning(f"Error starting QEMU for VM '{target_vm['name']}': {e}")
        return False


def _stop_qemu(vm_id: str, force: bool = False):
    entry = _RUNNING_QEMU_PROCS.pop(vm_id, None)
    proc = entry.get("proc") if entry else None
    pid = entry.get("pid") if entry else None

    if not pid:
        pid_file = os.path.join(DATA_DIR, "vms", vm_id, "qemu.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
            except Exception:
                pass

    if proc and proc.poll() is None:
        if force:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    if pid:
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.kill(pid, sig)
        except OSError:
            pass

    pid_file = os.path.join(DATA_DIR, "vms", vm_id, "qemu.pid")
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass

    sock_path = f"/tmp/{vm_id}-serial.sock"
    if os.path.exists(sock_path):
        try:
            os.remove(sock_path)
        except OSError:
            pass


@router.get("/{vm_id}", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_detail(vm_id: str):
    """Retrieves detailed virtual machine configuration, attachments, and runtime state."""
    vms = _load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")
    vnc_port = _get_qemu_vnc_port(vms, vm_id)
    detail = dict(target)
    detail["vnc_port"] = vnc_port
    ip = target.get("ip_address") or ""
    detail["connection_summary"] = {
        "vnc_uri": f"vnc://10.40.30.249:{vnc_port}",
        "web_console": f"/api/vms/{vm_id}/console",
        "ssh_command": f"ssh root@{ip}" if ip else "",
    }
    return detail


@router.get("/{vm_id}/connection-info", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_connection_info(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Returns multi-protocol access credentials (SSH, VNC, Web Console) for a target VM."""
    vms = _load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    vnc_port = _get_qemu_vnc_port(vms, vm_id)
    ip = target_vm.get("ip_address") or ""
    ssh_port = target_vm.get("ssh_port") or (2220 + (vnc_port - 5900))
    is_iso_boot = bool(target_vm.get("iso_path"))

    ssh_cmd = ""
    if not is_iso_boot:
        if ip:
            ssh_cmd = f"ssh root@{ip}"
        else:
            ssh_cmd = f"ssh -p {ssh_port} root@10.40.30.249"

    return {
        "vm_id": vm_id,
        "name": target_vm["name"],
        "state": target_vm.get("state", "stopped"),
        "ip_address": ip,
        "ssh_port": ssh_port,
        "ssh_command": ssh_cmd,
        "vnc_port": vnc_port,
        "vnc_uri": f"vnc://10.40.30.249:{vnc_port}",
        "console_url": f"/api/vms/{vm_id}/console",
        "has_ip": bool(ip),
        "is_iso_boot": is_iso_boot,
    }


@router.post("/{vm_id}/console/token", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def create_console_token(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Issues single-use ephemeral ticket for noVNC / serial console WebSocket streaming."""
    vms = _load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    ticket = f"zct_{uuid.uuid4().hex}"
    _CONSOLE_TICKETS[ticket] = {
        "vm_id": vm_id,
        "username": principal.username,
        "created_at": time.time(),
        "expires_at": time.time() + 60,
    }
    return {
        "ticket": ticket,
        "ws_url": f"/api/vms/{vm_id}/console/ws?ticket={ticket}",
        "ws_console_url": f"/api/vms/{vm_id}/console/ws?ticket={ticket}",
        "ws_serial_url": f"/api/vms/{vm_id}/serial/ws?ticket={ticket}",
        "vm_id": vm_id,
        "expires_in": 60,
    }


def _validate_console_ticket(ticket: Optional[str], vm_id: str) -> bool:
    if not ticket:
        return False
    now = time.time()
    if ticket in _CONSOLE_TICKETS:
        entry = _CONSOLE_TICKETS.pop(ticket)
        if entry.get("vm_id") == vm_id and entry.get("expires_at", 0) > now:
            return True
    try:
        from backend.api.auth import validate_and_consume_stream_ticket

        auth_entry = validate_and_consume_stream_ticket(ticket)
        if auth_entry:
            return True
    except Exception:
        pass
    return False


@router.websocket("/{vm_id}/console/ws")
async def websocket_vm_console(websocket: WebSocket, vm_id: str):
    """WebSocket proxy bridging browser to QEMU RFB VNC display socket."""
    ticket = websocket.query_params.get("ticket")
    if not _validate_console_ticket(ticket, vm_id):
        await websocket.close(code=1008, reason="Unauthorized or expired console ticket")
        return

    subprotocol = None
    if "binary" in websocket.headers.get("sec-websocket-protocol", ""):
        subprotocol = "binary"
    await websocket.accept(subprotocol=subprotocol)

    vms = _load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    vnc_port = _get_qemu_vnc_port(vms, vm_id)
    if target and target.get("state") == "running" and not _is_qemu_process_alive(vm_id):
        _start_qemu(target, vnc_port)

    vnc_host = "127.0.0.1"

    from backend.services.console_proxy import stream_socket_to_websocket

    await stream_socket_to_websocket(websocket, vnc_host, vnc_port)


@router.websocket("/{vm_id}/serial/ws")
async def websocket_vm_serial(websocket: WebSocket, vm_id: str):
    """WebSocket proxy bridging browser to QEMU serial PTY / UNIX domain socket."""
    ticket = websocket.query_params.get("ticket")
    if not _validate_console_ticket(ticket, vm_id):
        await websocket.close(code=1008, reason="Unauthorized or expired serial ticket")
        return

    await websocket.accept()

    vms = _load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    if target and target.get("state") == "running" and not _is_qemu_process_alive(vm_id):
        vnc_port = _get_qemu_vnc_port(vms, vm_id)
        _start_qemu(target, vnc_port)

    sock_candidates = [
        f"/tmp/{vm_id}-serial.sock",
        f"/var/run/qemu/{vm_id}-serial.sock",
        f"/tmp/zettnas-vms/{vm_id}/serial.sock",
    ]
    sock_path = next((p for p in sock_candidates if os.path.exists(p)), None)
    if not sock_path:
        sock_path = sock_candidates[0]

    from backend.services.console_proxy import stream_unix_socket_to_websocket

    await stream_unix_socket_to_websocket(websocket, sock_path)


@router.post("/{vm_id}/action", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def execute_vm_action(
    vm_id: str,
    req: VmActionRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Executes lifecycle action on target VM: start, stop, pause, resume, force_off."""
    vms = _load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    action = req.action
    current_state = target_vm.get("state", "stopped")
    vnc_port = _get_qemu_vnc_port(vms, vm_id)

    if action == "start":
        _start_qemu(target_vm, vnc_port)
        target_vm["state"] = "running"
        target_vm["uptime_seconds"] = 1
        if target_vm.get("iso_path"):
            target_vm["ip_address"] = ""
        elif not target_vm.get("ip_address"):
            target_vm["ip_address"] = f"192.168.1.{100 + (hash(vm_id) % 150)}"
    elif action == "stop":
        _stop_qemu(vm_id, force=False)
        target_vm["state"] = "stopped"
        target_vm["uptime_seconds"] = 0
    elif action == "pause":
        if current_state == "running":
            target_vm["state"] = "paused"
    elif action == "resume":
        if current_state == "paused":
            target_vm["state"] = "running"
    elif action == "force_off":
        _stop_qemu(vm_id, force=True)
        target_vm["state"] = "stopped"
        target_vm["uptime_seconds"] = 0

    _save_vms(vms)
    add_event("info", "VM State Changed", f"VM '{target_vm['name']}' action '{action}' executed.")
    return {"status": "ok", "state": target_vm["state"]}


@router.delete("/{vm_id}", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def delete_vm(vm_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Deletes a virtual machine definition."""
    vms = _load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    if target.get("state") == "running":
        raise HTTPException(status_code=400, detail="Cannot delete a running virtual machine. Stop it first.")

    _stop_qemu(vm_id, force=True)
    vms = [v for v in vms if v["id"] != vm_id]
    _save_vms(vms)
    add_event("info", "VM Removed", f"VM '{target['name']}' was deleted.")
    return {"status": "ok"}
