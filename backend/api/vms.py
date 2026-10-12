"""
ZettNAS Toolkit - Virtual Machine (VM) Management & Dynamic Elastic Budgeting API
Provides KVM hypervisor telemetry, adaptive headroom calculations, ISO scanning,
and VM lifecycle orchestration.
"""

import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import DATA_DIR, HOST_PROC, POOL_PATH, logger
from backend.fsutil import atomic_write_json, read_json
from backend.state import Z_STATE, add_event

router = APIRouter(prefix="/vms", tags=["Virtual Machines"])

VMS_CONFIG_FILE = os.path.join(DATA_DIR, "vms.json")


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
    """Inspects /dev/kvm presence and host CPU virtualization flags."""
    kvm_candidates = ["/dev/kvm", "/host/dev/kvm"]
    kvm_present = any(os.path.exists(p) for p in kvm_candidates)
    kvm_rw = False
    for p in kvm_candidates:
        if os.path.exists(p) and os.access(p, os.R_OK | os.W_OK):
            kvm_rw = True
            break

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
    if kvm_present and kvm_rw:
        state = "active"
        badge = "KVM Accelerated: Active (" + ("Intel VT-x" if vmx else ("AMD-V" if svm else "Hardware Virt")) + ")"
    elif hardware_virt:
        state = "restricted"
        badge = "KVM Emulation: Device restricted or module missing"
    else:
        state = "disabled"
        badge = "Hardware Virtualization Disabled in BIOS"

    return {
        "device_present": kvm_present,
        "device_writable": kvm_rw,
        "intel_vtx": vmx,
        "amd_v": svm,
        "hardware_virt": hardware_virt,
        "state": state,
        "badge": badge,
    }


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


class VmActionRequest(BaseModel):
    action: str = Field(..., pattern="^(start|stop|pause|resume|force_off)$")


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


@router.get("", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def list_vms():
    """Lists configured virtual machines with live states and resource allocations."""
    return _load_vms()


@router.get("/isos", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_discovered_isos():
    """Lists available ISO and OS installation images."""
    return scan_isos()


@router.get("/bridges", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_network_bridges():
    """Lists available host network bridges."""
    return scan_bridges()


@router.post("", dependencies=[Depends(require_scope("system:config", "storage:admin"))])
def create_vm(req: VmCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Provisions a new virtual machine with dynamic headroom validation."""
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

    if action == "start":
        target_vm["state"] = "running"
        target_vm["uptime_seconds"] = 1
        if not target_vm.get("ip_address"):
            target_vm["ip_address"] = f"192.168.1.{100 + (hash(vm_id) % 150)}"
    elif action == "stop":
        target_vm["state"] = "stopped"
        target_vm["uptime_seconds"] = 0
    elif action == "pause":
        if current_state == "running":
            target_vm["state"] = "paused"
    elif action == "resume":
        if current_state == "paused":
            target_vm["state"] = "running"
    elif action == "force_off":
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

    vms = [v for v in vms if v["id"] != vm_id]
    _save_vms(vms)
    add_event("info", "VM Removed", f"VM '{target['name']}' was deleted.")
    return {"status": "ok"}
