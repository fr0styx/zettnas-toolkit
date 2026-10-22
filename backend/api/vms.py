"""
ZettNAS Toolkit - Virtual Machine (VM) Management & Dynamic Elastic Budgeting API
Provides KVM hypervisor telemetry, adaptive headroom calculations, ISO scanning,
and VM lifecycle orchestration.
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
from backend.services.vm_engine import QmpEngine
from backend.state import Z_STATE, add_event

router = APIRouter(prefix="/vms", tags=["Virtual Machines"])

# Split into service modules (ARC-01); names stay importable from here.
from backend.services import vm_guest, vm_host, vm_qemu, vm_store  # noqa: E402, F401
from backend.services.vm_guest import (  # noqa: E402, F401
    _VM_IP_BACKGROUND,
    _VM_IP_CACHE,
    _VM_IP_LOCK,
    _VM_IP_REFRESHING,
    VM_IP_TTL_SECS,
    _cached_vm_ip,
    _forget_vm_ip,
    _qga_command,
    _qga_guest_ipv4,
    _qga_socket_path,
    _refresh_vm_ip,
    _resolve_vm_ip_by_mac,
)
from backend.services.vm_host import (  # noqa: E402, F401
    _PCI_SLOT_RE,
    _PCI_SYSFS_BASES,
    _VFIO_NODES,
    _can_use_kvm,
    _ensure_vfio_dev,
    _find_ovmf_firmware,
    _get_host_ip,
    _get_host_memory_bytes,
    _get_target_iso_dir,
    _image_variant,
    _normalize_pci_slot,
    _pci_device_driver,
    _pci_passthrough_problem,
    _sanitize_pci_list,
    _swtpm_binary,
    _vfio_available,
    calculate_cpu_capacity,
    calculate_vm_budget,
    get_kvm_status,
    scan_bridges,
    scan_host_usb_devices,
    scan_isos,
)
from backend.services.vm_qemu import (  # noqa: E402, F401
    _QMP_ENGINE,
    _QMP_EVENT_LOG,
    _drain_stderr,
    _get_qemu_vnc_port,
    _is_qemu_process_alive,
    _load_vms,
    _on_qmp_event,
    _prepare_vtpm,
    _qmp_command,
    _qmp_socket_path,
    _reconcile_vm_states,
    _save_vms,
    _start_qemu,
    _sync_cleanup_qemu_process,
    async_stop_qemu,
)
from backend.services.vm_store import (  # noqa: E402, F401
    _ABORT_DOWNLOAD_TASKS,
    _CONSOLE_TICKETS,
    _DISK_BUSES,
    _DISK_FORMATS,
    _DOWNLOAD_TASKS,
    _LAST_QEMU_ERRORS,
    _QEMU_UNSAFE,
    _RUNNING_QEMU_PROCS,
    KVM_GET_API_VERSION,
    OFFICIAL_ISO_CATALOG,
    VMS_CONFIG_FILE,
    _confined,
    _validate_vm_inputs,
    _vm_disk_roots,
    _vm_iso_roots,
    _vm_share_roots,
)

# ---- Guest IP discovery: QEMU Guest Agent first, host ARP table second ----


# ---- Request / Response Models ----
class VmCreateRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str | None = ""
    os_family: str = Field("linux", pattern="^(linux|windows|bsd|other)$")
    vcpus: int = Field(2, ge=1, le=128)
    ram_gb: float = Field(4.0, ge=0.5, le=1024.0)
    disk_size_gb: int = Field(32, ge=5, le=4096)
    disk_format: str = Field("qcow2", pattern="^(qcow2|raw)$")
    disk_bus: str = Field("virtio", pattern="^(virtio|sata|nvme)$")
    iso_path: str | None = None
    bridge: str = Field("br0", min_length=2)
    autostart: bool = False
    override_limits: bool = False
    host_shares: list[dict[str, Any]] = Field(default_factory=list)
    secondary_disks: list[dict[str, Any]] = Field(default_factory=list)
    boot_order: str | None = Field("iso", pattern="^(iso|disk)$")
    firmware: str | None = Field("seabios", pattern="^(seabios|uefi)$")
    video_adapter: str | None = Field("virtio-gpu", pattern="^(virtio-gpu|qxl|vga|none)$")
    display_adapter: str | None = None
    tpm_enabled: bool | None = False
    usb_passthrough: list[dict[str, Any]] = Field(default_factory=list)
    sockets: int | None = Field(None, ge=1, le=16)
    cores: int | None = Field(None, ge=1, le=128)
    threads: int | None = Field(None, ge=1, le=4)
    cpu_affinity: list[int] | None = None
    pci_passthrough: list[dict[str, Any]] = Field(default_factory=list)


class VmUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    vcpus: int | None = Field(None, ge=1, le=128)
    ram_gb: float | None = Field(None, ge=0.5, le=1024.0)
    iso_path: str | None = None
    boot_order: str | None = Field(None, pattern="^(iso|disk)$")
    autostart: bool | None = None
    override_limits: bool | None = None
    secondary_disks: list[dict[str, Any]] | None = None
    host_shares: list[dict[str, Any]] | None = None
    firmware: str | None = Field(None, pattern="^(seabios|uefi)$")
    video_adapter: str | None = Field(None, pattern="^(virtio-gpu|qxl|vga|none)$")
    display_adapter: str | None = None
    tpm_enabled: bool | None = None
    usb_passthrough: list[dict[str, Any]] | None = None
    sockets: int | None = Field(None, ge=1, le=16)
    cores: int | None = Field(None, ge=1, le=128)
    threads: int | None = Field(None, ge=1, le=4)
    cpu_affinity: list[int] | None = None
    pci_passthrough: list[dict[str, Any]] | None = None


class VmSnapshotCreateRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-zA-Z0-9_-]{1,64}$", description="Snapshot tag/name")
    description: str | None = Field(None, max_length=256)


class VmActionRequest(BaseModel):
    action: str = Field(..., pattern="^(start|stop|restart|reboot|pause|resume|force_off|acpi_shutdown)$")


class VmDiskResizeRequest(BaseModel):
    new_size_gb: int = Field(..., ge=1, le=16384, description="Target expanded disk size in Gigabytes")
    disk_index: int | None = Field(0, ge=0, description="0 for primary disk, 1..N for secondary disks")


def _download_iso_worker(task_id: str, catalog_item: dict[str, Any], target_dir: str):
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
        from backend.services.safe_fetch import safe_open

        with (
            safe_open(url, context="public", headers={"User-Agent": "ZettNAS-Hypervisor/2.0"}, timeout=30) as resp,
            open(tmp_path, "wb") as f,
        ):
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
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
    total_mem = vm_host._get_host_memory_bytes()
    vms = vm_qemu._load_vms()
    host_threads = os.cpu_count() or 8

    budget = vm_host.calculate_vm_budget(total_mem, vms)
    cpu_cap = vm_host.calculate_cpu_capacity(host_threads, vms)
    kvm = vm_host.get_kvm_status()

    return {
        "kvm": kvm,
        "memory_budget": budget,
        "cpu_capacity": cpu_cap,
        "active_vm_count": len([v for v in vms if v.get("state") == "running"]),
        "total_vm_count": len(vms),
    }


def collect_vm_diagnostics() -> dict[str, Any]:
    """Aggregates hypervisor telemetry, VM fleet status, and error logs for diagnostics bundles."""
    telemetry = get_vms_telemetry()
    vms = vm_qemu._load_vms()
    recent_errors: dict[str, list[str]] = {}
    for vm in vms:
        vm_id = vm.get("id")
        vm_dir = os.path.join(DATA_DIR, "vms", vm_id) if vm_id else None
        if vm_dir and os.path.isdir(vm_dir):
            err_log = os.path.join(vm_dir, "qemu_last_error.log")
            if os.path.exists(err_log):
                try:
                    with open(err_log, encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()
                        if lines:
                            recent_errors[vm_id] = [line.strip() for line in lines[-50:]]
                except Exception:
                    logger.debug("backend.api.vms.collect_vm_diagnostics: ignored error", exc_info=True)

    return {
        "hypervisor_telemetry": telemetry,
        "vms_inventory": vms,
        "recent_qemu_errors": recent_errors,
    }


@router.get("/kvm/diagnose", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_kvm_diagnose():
    """Returns detailed multi-tier KVM diagnostic report including host hardware and cgroup analysis."""
    return vm_host.get_kvm_status()


@router.get("", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def list_vms():
    """Lists configured virtual machines with live states and resource allocations."""
    vms = vm_qemu._load_vms()
    for vm in vms:
        if vm.get("state") == "running":
            ip = vm_guest._cached_vm_ip(vm)
            if ip:
                vm["ip_address"] = ip
    return vms


@router.get("/isos", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_discovered_isos():
    """Lists available ISO and OS installation images."""
    return vm_host.scan_isos()


def _write_and_hash_chunk(f, data: bytes, hasher) -> None:
    f.write(data)
    hasher.update(data)


@router.post("/isos/upload", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
async def upload_iso_file(
    request: Request,
    filename: str | None = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Streams uploaded ISO file directly into NAS storage (/mnt/user/isos)."""
    target_dir = vm_host._get_target_iso_dir()
    raw_name = filename or request.headers.get("x-filename") or f"uploaded-{uuid.uuid4().hex[:6]}.iso"
    clean_name = os.path.basename(raw_name)
    if not clean_name.lower().endswith((".iso", ".img")):
        clean_name += ".iso"

    upload_id = uuid.uuid4().hex[:8]
    tmp_path = os.path.join(target_dir, f".tmp_{upload_id}_{clean_name}")
    out_path = os.path.join(target_dir, clean_name)
    total_written = 0
    hasher = hashlib.sha256()

    buffer = bytearray()
    CHUNK_FLUSH_SIZE = 4 * 1024 * 1024  # 4 MB

    try:
        with open(tmp_path, "wb") as f:
            async for chunk in request.stream():
                if chunk:
                    buffer.extend(chunk)
                    total_written += len(chunk)
                    if len(buffer) >= CHUNK_FLUSH_SIZE:
                        flush_bytes = bytes(buffer)
                        buffer.clear()
                        await asyncio.to_thread(_write_and_hash_chunk, f, flush_bytes, hasher)
            if buffer:
                flush_bytes = bytes(buffer)
                buffer.clear()
                await asyncio.to_thread(_write_and_hash_chunk, f, flush_bytes, hasher)
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to upload ISO: {e}") from e

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
            logger.debug("backend.api.vms.upload_iso_file: ignored error", exc_info=True)

    try:
        os.replace(tmp_path, out_path)
    except OSError as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Failed to commit uploaded ISO: {e}") from e

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


@router.delete("/isos", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
def delete_iso_image(
    path: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    allowed_dirs = [
        "/mnt/user/isos",
        "/mnt/user/system/isos",
        "/mnt/storage/isos",
        os.path.join(POOL_PATH, "isos"),
        os.path.join(DATA_DIR, "isos"),
    ]
    real_path = resolve_within(path, allowed_dirs)
    if not real_path:
        raise HTTPException(status_code=400, detail="Invalid ISO path outside authorized repositories.")

    if not os.path.exists(real_path):
        raise HTTPException(status_code=404, detail="ISO file not found.")

    try:
        os.remove(real_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete ISO file: {e}") from e

    add_event("info", "ISO Removed", f"ISO '{os.path.basename(real_path)}' was deleted from repository.")
    return {"status": "ok"}


@router.get("/catalog", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_official_catalog():
    """Lists curated official distribution images with local cache detection."""
    local_isos = vm_host.scan_isos()
    local_filenames = {iso["name"].lower() for iso in local_isos}

    results = []
    for item in OFFICIAL_ISO_CATALOG:
        is_dl = item["filename"].lower() in local_filenames
        entry = dict(item)
        entry["downloaded"] = is_dl
        results.append(entry)
    return results


@router.post("/catalog/{catalog_id}/download", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
def download_official_iso(
    catalog_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Initiates a background download of a verified official distribution ISO."""
    item = next((c for c in OFFICIAL_ISO_CATALOG if c["id"] == catalog_id), None)
    if not item:
        raise HTTPException(status_code=404, detail=f"Catalog ISO '{catalog_id}' not found.")

    target_dir = vm_host._get_target_iso_dir()
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


@router.delete("/catalog/tasks/{task_id}", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
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
    return vm_host.scan_bridges()


@router.get("/usb-devices", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_host_usb_devices():
    """Lists physical and virtual USB devices connected to the host."""
    return vm_host.scan_host_usb_devices()


@router.post("", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
def create_vm(req: VmCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Provisions a new virtual machine with dynamic headroom validation and volume mappings."""
    vm_store._validate_vm_inputs(req.secondary_disks, req.iso_path, req.host_shares)
    vms = vm_qemu._load_vms()
    if any(v["name"].lower() == req.name.lower() for v in vms):
        raise HTTPException(status_code=400, detail=f"Virtual machine '{req.name}' already exists.")

    total_mem = vm_host._get_host_memory_bytes()
    budget = vm_host.calculate_vm_budget(total_mem, vms)

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
        "boot_order": req.boot_order or "iso",
        "firmware": req.firmware or "seabios",
        "video_adapter": req.video_adapter or req.display_adapter or "virtio-gpu",
        "tpm_enabled": bool(req.tpm_enabled),
        "usb_passthrough": req.usb_passthrough or [],
        "pci_passthrough": vm_host._sanitize_pci_list(req.pci_passthrough),
        "created_at": int(time.time()),
    }

    vms.append(new_vm)
    vm_qemu._save_vms(vms)

    add_event(
        "info",
        "Virtual Machine Created",
        f"VM '{req.name}' created ({req.vcpus} vCPUs, {req.ram_gb} GB RAM).",
    )
    return new_vm


# ---- Host PCI / GPU passthrough (VFIO) ----


@router.get("/iommu-groups", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_host_iommu_groups():
    """Scans Linux host sysfs /sys/kernel/iommu_groups to report IOMMU isolation groups and PCI devices."""
    iommu_path = "/sys/kernel/iommu_groups"
    if not os.path.exists(iommu_path):
        iommu_path = "/host/sys/kernel/iommu_groups"

    has_iommu = os.path.exists(iommu_path)
    groups = []

    if has_iommu:
        try:
            for group_dir in sorted(os.listdir(iommu_path), key=lambda x: int(x) if x.isdigit() else 999):
                full_group = os.path.join(iommu_path, group_dir, "devices")
                if not os.path.isdir(full_group):
                    continue
                devs = []
                for pci_slot in sorted(os.listdir(full_group)):
                    dev_path = os.path.join(full_group, pci_slot)
                    vendor_id = ""
                    device_id = ""
                    dev_class = ""
                    try:
                        vfile = os.path.join(dev_path, "vendor")
                        if os.path.exists(vfile):
                            with open(vfile) as f:
                                vendor_id = f.read().strip().replace("0x", "")
                        dfile = os.path.join(dev_path, "device")
                        if os.path.exists(dfile):
                            with open(dfile) as f:
                                device_id = f.read().strip().replace("0x", "")
                        cfile = os.path.join(dev_path, "class")
                        if os.path.exists(cfile):
                            with open(cfile) as f:
                                dev_class = f.read().strip().replace("0x", "")
                    except Exception:
                        logger.debug("backend.api.vms.get_host_iommu_groups: ignored error", exc_info=True)
                    devs.append(
                        {
                            "slot": pci_slot,
                            "driver": (drv := vm_host._pci_device_driver(pci_slot)),
                            "vfio_ready": drv == "vfio-pci",
                            "vendor_id": vendor_id,
                            "device_id": device_id,
                            "class_code": dev_class,
                            "name": f"PCI Device [{vendor_id}:{device_id}]",
                        }
                    )
                groups.append(
                    {
                        "group_id": int(group_dir) if group_dir.isdigit() else group_dir,
                        "devices": devs,
                    }
                )
        except Exception as e:
            logger.warning(f"Error scanning IOMMU groups: {e}")

    return {
        "iommu_enabled": has_iommu and len(groups) > 0,
        "vfio_available": vm_host._vfio_available(),
        "total_groups": len(groups),
        "groups": groups,
    }


@router.get(
    "/backups",
    dependencies=[Depends(require_scope("system:view", "storage:read"))],
)
async def list_all_virtual_machine_backups():
    """Lists all saved VM hyper-backup archives across all virtual machines."""
    from backend.services.app_backup import list_vm_backups

    try:
        backups = await asyncio.to_thread(list_vm_backups)
        return {"status": "ok", "backups": backups}
    except Exception as e:
        logger.error(f"[VM Backup] Failed listing all VM backups: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/backups/{backup_id}/restore",
    dependencies=[Depends(require_scope("vms:manage", "system:config"))],
)
async def restore_virtual_machine_backup(backup_id: str):
    """Restores VM configuration and disk images from hyper-backup archive."""
    from backend.services.app_backup import restore_vm_backup

    try:
        res = await asyncio.to_thread(restore_vm_backup, backup_id)
        return {"status": "ok", "result": res}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve)) from ve
    except FileNotFoundError as fe:
        raise HTTPException(status_code=404, detail=str(fe)) from fe
    except Exception as e:
        logger.error(f"[VM Backup] Restore failed for {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/backups/{backup_id}",
    dependencies=[
        Depends(require_scope("vms:manage", "system:config")),
        Depends(require_confirmation("backup.delete")),
    ],
)
async def delete_virtual_machine_backup(backup_id: str):
    """Deletes a VM hyper-backup archive from disk and updates registry."""
    from backend.services.app_backup import delete_vm_backup

    try:
        ok = await asyncio.to_thread(delete_vm_backup, backup_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Backup record not found.")
        return {"status": "ok", "deleted": True, "backup_id": backup_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VM Backup] Failed deleting backup {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{vm_id}", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_detail(vm_id: str):
    """Retrieves detailed virtual machine configuration, attachments, and runtime state."""
    vms = vm_qemu._load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    vnc_port = vm_qemu._get_qemu_vnc_port(vms, vm_id)
    detail = dict(target)
    detail["vnc_port"] = vnc_port
    detail["is_alive"] = vm_qemu._is_qemu_process_alive(vm_id)
    detail["last_error"] = target.get("last_error")
    detail["network_mode"] = target.get("network_mode", "slirp")
    ip = target.get("ip_address") or ""
    host_ip = vm_host._get_host_ip()
    detail["connection_summary"] = {
        "vnc_uri": f"vnc://{host_ip}:{vnc_port}",
        "web_console": f"/api/vms/{vm_id}/console",
        "ssh_command": f"ssh root@{ip}" if ip else "",
    }
    return detail


@router.put("/{vm_id}", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
@router.patch("/{vm_id}", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
def update_vm(
    vm_id: str,
    req: VmUpdateRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Updates virtual machine configuration (RAM, vCPUs, name, description, ISO path, boot order, autostart)."""
    vm_store._validate_vm_inputs(req.secondary_disks, req.iso_path, req.host_shares)
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    is_running = vm_qemu._is_qemu_process_alive(vm_id) or target_vm.get("state") == "running"

    if req.name is not None and req.name.strip():
        new_name = req.name.strip()
        if any(v["id"] != vm_id and v["name"].lower() == new_name.lower() for v in vms):
            raise HTTPException(status_code=400, detail=f"Virtual machine '{new_name}' already exists.")
        target_vm["name"] = new_name

    if req.description is not None:
        target_vm["description"] = req.description

    if req.vcpus is not None:
        if is_running and req.vcpus != target_vm.get("vcpus"):
            raise HTTPException(status_code=400, detail="Cannot alter vCPUs while VM is running. Stop it first.")
        target_vm["vcpus"] = req.vcpus

    if req.ram_gb is not None:
        if is_running and req.ram_gb != target_vm.get("ram_gb"):
            raise HTTPException(status_code=400, detail="Cannot alter RAM while VM is running. Stop it first.")
        target_vm["ram_gb"] = req.ram_gb

    if req.iso_path is not None:
        target_vm["iso_path"] = req.iso_path.strip() if req.iso_path and req.iso_path.strip() else None

    if req.boot_order is not None:
        target_vm["boot_order"] = req.boot_order

    if req.autostart is not None:
        target_vm["autostart"] = req.autostart

    if req.override_limits is not None:
        target_vm["override_active"] = req.override_limits

    if req.secondary_disks is not None:
        target_vm["secondary_disks"] = req.secondary_disks

    if req.host_shares is not None:
        target_vm["host_shares"] = req.host_shares

    if req.firmware is not None:
        target_vm["firmware"] = req.firmware

    if req.video_adapter is not None or req.display_adapter is not None:
        target_vm["video_adapter"] = req.video_adapter or req.display_adapter

    if req.tpm_enabled is not None:
        target_vm["tpm_enabled"] = bool(req.tpm_enabled)

    if req.usb_passthrough is not None:
        target_vm["usb_passthrough"] = req.usb_passthrough
    if req.pci_passthrough is not None:
        target_vm["pci_passthrough"] = vm_host._sanitize_pci_list(req.pci_passthrough)

    vm_qemu._save_vms(vms)
    add_event("info", "VM Updated", f"VM '{target_vm['name']}' configuration updated.")
    return target_vm


@router.get("/{vm_id}/connection-info", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_connection_info(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Returns multi-protocol access credentials (SSH, VNC, Web Console) for a target VM."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    vnc_port = vm_qemu._get_qemu_vnc_port(vms, vm_id)
    ip = target_vm.get("ip_address") or ""
    ssh_port = target_vm.get("ssh_port") or (2220 + (vnc_port - 5900))
    is_iso_boot = bool(target_vm.get("iso_path"))

    host_ip = vm_host._get_host_ip()
    ssh_cmd = ""
    if not is_iso_boot:
        if ip:
            ssh_cmd = f"ssh root@{ip}"
        else:
            ssh_cmd = f"ssh -p {ssh_port} root@{host_ip}"

    return {
        "vm_id": vm_id,
        "name": target_vm["name"],
        "state": target_vm.get("state", "stopped"),
        "ip_address": ip,
        "ssh_port": ssh_port,
        "ssh_command": ssh_cmd,
        "vnc_port": vnc_port,
        "vnc_uri": f"vnc://{host_ip}:{vnc_port}",
        "console_url": f"/api/vms/{vm_id}/console",
        "has_ip": bool(ip),
        "is_iso_boot": is_iso_boot,
    }


@router.post(
    "/{vm_id}/console/token", dependencies=[Depends(require_scope("vms:write", "vms:manage", "system:config"))]
)
def create_console_token(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Issues single-use ephemeral ticket for noVNC / serial console WebSocket streaming."""
    vms = vm_qemu._load_vms()
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


def _validate_console_ticket(ticket: str | None, vm_id: str) -> bool:
    if not ticket:
        return False
    now = time.time()
    # Prune expired tickets
    expired = [k for k, v in _CONSOLE_TICKETS.items() if v.get("expires_at", 0) <= now]
    for k in expired:
        _CONSOLE_TICKETS.pop(k, None)

    if ticket in _CONSOLE_TICKETS:
        entry = _CONSOLE_TICKETS.pop(ticket)
        if entry.get("vm_id") == vm_id and entry.get("expires_at", 0) > now:
            return True
    allowed_console_scopes = (
        "*",
        "vms:*",
        "vms:console",
        "vms:write",
        "vms:manage",
        "system:config",
        "storage:admin",
    )
    try:
        from backend.auth import AuthenticatedPrincipal, get_current_session
        from backend.users_db import validate_scoped_api_token, validate_user_session

        sess = get_current_session(ticket)
        if not sess:
            sess = validate_user_session(ticket)
        if not sess:
            api_tok = validate_scoped_api_token(ticket)
            if api_tok:
                sess = {
                    "user_id": api_tok.get("user_id"),
                    "username": api_tok.get("username"),
                    "role_id": api_tok.get("role_id"),
                    "scopes": api_tok.get("scopes", []),
                    "is_api_token": True,
                }
        if sess:
            principal = AuthenticatedPrincipal(sess)
            if principal.has_any_scope(*allowed_console_scopes):
                return True
    except Exception:
        logger.debug("backend.api.vms._validate_console_ticket: ignored error", exc_info=True)
    try:
        from backend.api.auth import validate_and_consume_stream_ticket
        from backend.auth import AuthenticatedPrincipal

        auth_entry = validate_and_consume_stream_ticket(ticket)
        if auth_entry:
            principal = AuthenticatedPrincipal(auth_entry)
            if principal.has_any_scope(*allowed_console_scopes):
                return True
    except Exception:
        logger.debug("backend.api.vms._validate_console_ticket: ignored error", exc_info=True)
    return False


@router.websocket("/{vm_id}/console/ws")
async def websocket_vm_console(websocket: WebSocket, vm_id: str):
    """WebSocket proxy bridging browser to QEMU RFB VNC display socket."""
    ticket = (
        websocket.query_params.get("ticket")
        or websocket.query_params.get("token")
        or websocket.cookies.get("session_token")
        or websocket.cookies.get("zettnas_session")
        or websocket.cookies.get("zat_token")
    )
    if not _validate_console_ticket(ticket, vm_id):
        await websocket.close(code=1008, reason="Unauthorized or expired console ticket")
        return

    is_cookie_auth = (
        not websocket.query_params.get("ticket")
        and not websocket.query_params.get("token")
        and bool(
            websocket.cookies.get("session_token")
            or websocket.cookies.get("zettnas_session")
            or websocket.cookies.get("zat_token")
        )
    )
    from backend.auth import validate_websocket_origin

    if not validate_websocket_origin(websocket, is_cookie_auth=is_cookie_auth):
        await websocket.close(code=1008, reason="Forbidden origin")
        return

    subprotocols = [s.strip() for s in websocket.headers.get("sec-websocket-protocol", "").split(",") if s.strip()]
    subprotocol = "binary" if "binary" in subprotocols else (subprotocols[0] if subprotocols else None)
    await websocket.accept(subprotocol=subprotocol)

    vms = vm_qemu._load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    vnc_port = vm_qemu._get_qemu_vnc_port(vms, vm_id)
    if target and target.get("state") == "running" and not vm_qemu._is_qemu_process_alive(vm_id):
        ok, err = await asyncio.to_thread(vm_qemu._start_qemu, target, vnc_port)
        if not ok:
            await websocket.close(code=1011, reason=f"VM startup failed: {err}")
            return

    vnc_host = "127.0.0.1"

    from backend.services.console_proxy import stream_socket_to_websocket

    await stream_socket_to_websocket(websocket, vnc_host, vnc_port)


@router.websocket("/{vm_id}/serial/ws")
async def websocket_vm_serial(websocket: WebSocket, vm_id: str):
    """WebSocket proxy bridging browser to QEMU serial PTY / UNIX domain socket."""
    ticket = (
        websocket.query_params.get("ticket")
        or websocket.query_params.get("token")
        or websocket.cookies.get("session_token")
        or websocket.cookies.get("zettnas_session")
        or websocket.cookies.get("zat_token")
    )
    if not _validate_console_ticket(ticket, vm_id):
        await websocket.close(code=1008, reason="Unauthorized or expired serial ticket")
        return

    is_cookie_auth = (
        not websocket.query_params.get("ticket")
        and not websocket.query_params.get("token")
        and bool(
            websocket.cookies.get("session_token")
            or websocket.cookies.get("zettnas_session")
            or websocket.cookies.get("zat_token")
        )
    )
    from backend.auth import validate_websocket_origin

    if not validate_websocket_origin(websocket, is_cookie_auth=is_cookie_auth):
        await websocket.close(code=1008, reason="Forbidden origin")
        return

    await websocket.accept()

    vms = vm_qemu._load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    if target and target.get("state") == "running" and not vm_qemu._is_qemu_process_alive(vm_id):
        vnc_port = vm_qemu._get_qemu_vnc_port(vms, vm_id)
        ok, err = await asyncio.to_thread(vm_qemu._start_qemu, target, vnc_port)
        if not ok:
            await websocket.close(code=1011, reason=f"VM startup failed: {err}")
            return

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


@router.post("/{vm_id}/action", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
async def execute_vm_action(
    vm_id: str,
    req: VmActionRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Executes lifecycle action on target VM: start, stop, restart, reboot, acpi_shutdown, pause, resume, force_off."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    action = req.action
    current_state = target_vm.get("state", "stopped")
    vnc_port = vm_qemu._get_qemu_vnc_port(vms, vm_id)

    if action == "start":
        vm_guest._forget_vm_ip(vm_id)
        ok, err_msg = await asyncio.to_thread(vm_qemu._start_qemu, target_vm, vnc_port)
        if not ok:
            target_vm["state"] = "stopped"
            target_vm["last_error"] = err_msg
            vm_qemu._save_vms(vms)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to start virtual machine '{target_vm['name']}': {err_msg}",
            )
        target_vm["state"] = "running"
        target_vm["last_error"] = None
        target_vm["uptime_seconds"] = 1
        if target_vm.get("iso_path"):
            target_vm["ip_address"] = ""
        else:
            resolved_ip = vm_guest._resolve_vm_ip_by_mac(target_vm.get("mac") or "")
            target_vm["ip_address"] = resolved_ip or target_vm.get("ip_address") or ""

    elif action == "stop":
        await vm_qemu.async_stop_qemu(vm_id, force=False)
        target_vm["state"] = "stopped"
        target_vm["uptime_seconds"] = 0

    elif action == "acpi_shutdown":
        qmp_res = await asyncio.to_thread(vm_qemu._qmp_command, vm_id, "system_powerdown")
        if "error" in qmp_res:
            await vm_qemu.async_stop_qemu(vm_id, force=False)
        target_vm["state"] = "stopped"
        target_vm["uptime_seconds"] = 0

    elif action in ("restart", "reboot"):
        qmp_res = await asyncio.to_thread(vm_qemu._qmp_command, vm_id, "system_reset")
        if "return" not in qmp_res:
            await vm_qemu.async_stop_qemu(vm_id, force=False)
            await asyncio.sleep(0.5)
            ok, err_msg = await asyncio.to_thread(vm_qemu._start_qemu, target_vm, vnc_port)
            if not ok:
                target_vm["state"] = "stopped"
                target_vm["last_error"] = err_msg
                vm_qemu._save_vms(vms)
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to restart VM '{target_vm['name']}': {err_msg}",
                )
        target_vm["state"] = "running"
        target_vm["uptime_seconds"] = 1

    elif action == "pause":
        if current_state == "running":
            await asyncio.to_thread(vm_qemu._qmp_command, vm_id, "stop")
            target_vm["state"] = "paused"

    elif action == "resume":
        if current_state == "paused":
            await asyncio.to_thread(vm_qemu._qmp_command, vm_id, "cont")
            target_vm["state"] = "running"

    elif action == "force_off":
        await vm_qemu.async_stop_qemu(vm_id, force=True)
        target_vm["state"] = "stopped"
        target_vm["uptime_seconds"] = 0

    vm_qemu._save_vms(vms)
    add_event("info", "VM State Changed", f"VM '{target_vm['name']}' action '{action}' executed.")
    return {"status": "ok", "state": target_vm["state"]}


@router.post("/{vm_id}/start", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
async def start_vm(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Starts the target virtual machine."""
    return await execute_vm_action(vm_id, VmActionRequest(action="start"), principal)


@router.post("/{vm_id}/stop", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
async def stop_vm(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Stops the target virtual machine."""
    return await execute_vm_action(vm_id, VmActionRequest(action="stop"), principal)


@router.post("/{vm_id}/restart", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
async def restart_vm(
    vm_id: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Restarts the target virtual machine."""
    return await execute_vm_action(vm_id, VmActionRequest(action="restart"), principal)


@router.get("/{vm_id}/error", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_error(vm_id: str):
    """Returns the last recorded QEMU error or startup failure log for a virtual machine."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    err_log = os.path.join(vm_dir, "qemu_last_error.log")
    err_text = None
    if os.path.exists(err_log):
        try:
            with open(err_log, encoding="utf-8", errors="replace") as f:
                err_text = f.read().strip()
        except OSError:
            pass

    return {
        "vm_id": vm_id,
        "name": target_vm["name"],
        "has_error": bool(err_text or target_vm.get("last_error")),
        "last_error": err_text or target_vm.get("last_error"),
    }


@router.get("/{vm_id}/status", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_qmp_status(vm_id: str):
    """Queries live QMP monitor socket for hypervisor execution state and vCPU threads."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    is_alive = vm_qemu._is_qemu_process_alive(vm_id)
    if not is_alive:
        return {
            "vm_id": vm_id,
            "name": target_vm["name"],
            "state": "stopped",
            "qmp_connected": False,
            "running": False,
        }

    qmp_status = vm_qemu._qmp_command(vm_id, "query-status")
    qmp_cpus = vm_qemu._qmp_command(vm_id, "query-cpus-fast")

    return {
        "vm_id": vm_id,
        "name": target_vm["name"],
        "state": target_vm.get("state", "running"),
        "qmp_connected": "return" in qmp_status,
        "hypervisor_status": qmp_status.get("return", {}),
        "vcpus": qmp_cpus.get("return", []),
    }


@router.get("/{vm_id}/screenshot", dependencies=[Depends(require_scope("system:view", "storage:read"))])
def get_vm_screenshot(vm_id: str):
    """Captures and returns a live graphical screendump of the VM via QMP screendump."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    if not vm_qemu._is_qemu_process_alive(vm_id):
        raise HTTPException(status_code=400, detail="Cannot capture screenshot: VM is not running.")

    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    ppm_path = os.path.join(vm_dir, "screen.ppm")

    qmp_res = vm_qemu._qmp_command(vm_id, "screendump", {"filename": ppm_path})
    if "error" in qmp_res:
        raise HTTPException(status_code=500, detail=f"QMP screendump failed: {qmp_res['error']}")

    if not os.path.exists(ppm_path):
        raise HTTPException(status_code=500, detail="Screenshot file was not generated by hypervisor.")

    try:
        import io

        from PIL import Image

        with Image.open(ppm_path) as img:
            out_buf = io.BytesIO()
            img.save(out_buf, format="PNG")
            png_bytes = out_buf.getvalue()

        try:
            os.remove(ppm_path)
        except OSError:
            pass
        return Response(content=png_bytes, media_type="image/png")
    except Exception:
        return FileResponse(ppm_path, media_type="image/x-portable-pixmap")


@router.post("/{vm_id}/disk/resize", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
@router.post("/{vm_id}/resize-disk", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
def resize_vm_disk(
    vm_id: str,
    req: VmDiskResizeRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    Expands a virtual machine virtual disk (qcow2/raw) using qemu-img resize.
    Dynamically notifies hypervisor via QMP block_resize if the VM is running.
    """
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    os.makedirs(vm_dir, exist_ok=True)
    disk_index = req.disk_index or 0

    if disk_index == 0:
        disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")
        target_vm["disk_path"] = disk_path
        current_size_gb = int(target_vm.get("disk_size_gb", 32) or 32)
    else:
        sdisks = target_vm.get("secondary_disks", [])
        if disk_index - 1 >= len(sdisks):
            raise HTTPException(status_code=404, detail=f"Secondary disk index {disk_index} not found.")
        sdisk = sdisks[disk_index - 1]
        disk_path = sdisk.get("path") or os.path.join(vm_dir, f"{sdisk.get('name', f'disk_{disk_index - 1}')}.qcow2")
        current_size_gb = int(sdisk.get("size_gb", 20) or 20)

    if req.new_size_gb <= current_size_gb:
        raise HTTPException(
            status_code=400,
            detail=f"Target disk size ({req.new_size_gb} GB) must be larger than current size ({current_size_gb} GB). Disk shrinking is not supported.",
        )

    disk_fmt = "raw" if disk_path.endswith((".raw", ".img")) else "qcow2"
    if not os.path.exists(disk_path):
        # Create empty placeholder if it didn't exist yet
        try:
            qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
            if os.path.exists(qemu_img) or shutil.which(qemu_img):
                subprocess.run(
                    [qemu_img, "create", "-f", disk_fmt, disk_path, f"{req.new_size_gb}G"],
                    check=True,
                    capture_output=True,
                )
            else:
                with open(disk_path, "wb") as f:
                    f.truncate(req.new_size_gb * 1024 * 1024 * 1024)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to create disk image: {e}") from e
    else:
        qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
        if os.path.exists(qemu_img) or shutil.which(qemu_img):
            try:
                subprocess.run(
                    [qemu_img, "resize", "-f", disk_fmt, disk_path, f"{req.new_size_gb}G"],
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                raise HTTPException(status_code=500, detail=f"qemu-img resize failed: {e.stderr or e}") from e

    if vm_qemu._is_qemu_process_alive(vm_id):
        new_bytes = req.new_size_gb * 1024 * 1024 * 1024
        device_tag = "drive0" if disk_index == 0 else f"sdisk{disk_index - 1}"
        vm_qemu._qmp_command(vm_id, "block_resize", {"device": device_tag, "size": new_bytes})

    if disk_index == 0:
        target_vm["disk_size_gb"] = req.new_size_gb
    else:
        target_vm["secondary_disks"][disk_index - 1]["size_gb"] = req.new_size_gb

    vm_qemu._save_vms(vms)
    add_event(
        "info",
        "VM Disk Resized",
        f"Disk {disk_index} expanded from {current_size_gb} GB to {req.new_size_gb} GB for VM '{target_vm['name']}'.",
    )
    return {
        "status": "ok",
        "vm_id": vm_id,
        "disk_index": disk_index,
        "disk_path": disk_path,
        "previous_size_gb": current_size_gb,
        "new_size_gb": req.new_size_gb,
    }


@router.delete(
    "/{vm_id}",
    dependencies=[Depends(require_scope("vms:manage", "system:config")), Depends(require_confirmation("vm.delete"))],
)
def delete_vm(
    vm_id: str,
    purge_disks: bool = True,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Deletes a virtual machine definition and cleans up its virtual disk directory."""
    vms = vm_qemu._load_vms()
    target = next((v for v in vms if v["id"] == vm_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    if target.get("state") == "running":
        raise HTTPException(status_code=400, detail="Cannot delete a running virtual machine. Stop it first.")

    # Sync endpoint (runs in FastAPI's threadpool); a forced stop needs no ACPI wait.
    vm_qemu._sync_cleanup_qemu_process(vm_id, force=True)
    vms = [v for v in vms if v["id"] != vm_id]
    vm_qemu._save_vms(vms)
    if purge_disks:
        vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
        if os.path.exists(vm_dir):
            shutil.rmtree(vm_dir, ignore_errors=True)

    add_event("info", "VM Removed", f"VM '{target['name']}' was deleted.")
    return {"status": "ok"}


# ---- VM Snapshots Lifecycle & Host IOMMU Groups ----


def _get_vm_snapshots_metadata(vm_id: str) -> dict[str, Any]:
    meta_path = os.path.join(DATA_DIR, "vms", vm_id, "snapshots.json")
    if os.path.exists(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            logger.debug("backend.api.vms._get_vm_snapshots_metadata: ignored error", exc_info=True)
    return {}


def _save_vm_snapshots_metadata(vm_id: str, data: dict[str, Any]):
    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    os.makedirs(vm_dir, exist_ok=True)
    meta_path = os.path.join(vm_dir, "snapshots.json")
    try:
        atomic_write_json(meta_path, data)
    except Exception as e:
        logger.warning(f"[VM-{vm_id}] Failed saving snapshots metadata: {e}")


def _list_qcow2_snapshots(disk_path: str) -> list[dict[str, Any]]:
    if not os.path.exists(disk_path):
        return []
    qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
    if not os.path.exists(qemu_img):
        return []
    try:
        res = subprocess.run(
            [qemu_img, "snapshot", "-l", "-U", disk_path],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        lines = res.stdout.strip().splitlines()
        snapshots = []
        parsing = False
        for line in lines:
            if "ID" in line and "TAG" in line:
                parsing = True
                continue
            if parsing and line.strip():
                parts = line.split()
                if len(parts) >= 2:
                    snap_id = parts[0]
                    snap_tag = parts[1]
                    vm_size = parts[2] if len(parts) > 2 else "0 B"
                    date_str = " ".join(parts[3:5]) if len(parts) >= 5 else ""
                    snapshots.append(
                        {
                            "id": snap_id,
                            "tag": snap_tag,
                            "name": snap_tag,
                            "vm_size": vm_size,
                            "date": date_str,
                        }
                    )
        return snapshots
    except Exception as e:
        logger.warning(f"Failed listing qcow2 snapshots: {e}")
        return []


@router.get("/{vm_id}/snapshots", dependencies=[Depends(require_scope("system:view", "storage:read"))])
async def get_vm_snapshots(vm_id: str):
    """Lists snapshots for target virtual machine with QCOW2 internal and saved metadata."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")
    raw_snaps = await asyncio.to_thread(_list_qcow2_snapshots, disk_path)
    meta = await asyncio.to_thread(_get_vm_snapshots_metadata, vm_id)

    enriched = []
    for s in raw_snaps:
        name = s["name"]
        m = meta.get(name, {})
        enriched.append(
            {
                **s,
                "description": m.get("description", ""),
                "created_at": m.get("created_at", s.get("date", "")),
                "state_at_snapshot": m.get("state", "stopped"),
            }
        )

    for name, m in meta.items():
        if not any(s["name"] == name for s in enriched):
            enriched.append(
                {
                    "id": m.get("id", name),
                    "tag": name,
                    "name": name,
                    "vm_size": m.get("vm_size", "0 B"),
                    "date": m.get("created_at", ""),
                    "description": m.get("description", ""),
                    "created_at": m.get("created_at", ""),
                    "state_at_snapshot": m.get("state", "stopped"),
                }
            )

    return enriched


@router.post("/{vm_id}/snapshots", dependencies=[Depends(require_scope("vms:manage", "system:config"))])
async def create_vm_snapshot(vm_id: str, req: VmSnapshotCreateRequest):
    """Creates a live snapshot (savevm via QMP if running, qemu-img if stopped)."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    name = req.name.strip()
    is_running = target_vm.get("state") == "running" and vm_qemu._is_qemu_process_alive(vm_id)
    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")

    if is_running:
        cmd_str = f"savevm {name}"
        qmp_res = await asyncio.to_thread(
            vm_qemu._qmp_command, vm_id, "human-monitor-command", {"command-line": cmd_str}, 10.0
        )
        if "error" in qmp_res:
            raise HTTPException(status_code=500, detail=f"QMP savevm failed: {qmp_res['error']}")
    else:
        if not os.path.exists(disk_path):
            raise HTTPException(status_code=400, detail="Primary disk not found to snapshot.")
        qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
        try:
            await asyncio.to_thread(
                subprocess.run,
                [qemu_img, "snapshot", "-c", name, disk_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"qemu-img snapshot failed: {e.stderr or e}") from e

    meta = await asyncio.to_thread(_get_vm_snapshots_metadata, vm_id)
    meta[name] = {
        "id": name,
        "name": name,
        "description": req.description or "",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "state": target_vm.get("state", "stopped"),
    }
    await asyncio.to_thread(_save_vm_snapshots_metadata, vm_id, meta)
    add_event("info", "VM Snapshot Created", f"Snapshot '{name}' created for VM '{target_vm['name']}'.")
    return {"success": True, "name": name, "vm_id": vm_id}


@router.post(
    "/{vm_id}/snapshots/{snapshot_name}/revert",
    dependencies=[Depends(require_scope("vms:manage", "system:config"))],
)
async def revert_vm_snapshot(vm_id: str, snapshot_name: str):
    """Reverts virtual machine state to a named snapshot."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    name = snapshot_name.strip()
    is_running = target_vm.get("state") == "running" and vm_qemu._is_qemu_process_alive(vm_id)
    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")

    if is_running:
        cmd_str = f"loadvm {name}"
        qmp_res = await asyncio.to_thread(
            vm_qemu._qmp_command, vm_id, "human-monitor-command", {"command-line": cmd_str}, 10.0
        )
        if "error" in qmp_res:
            raise HTTPException(status_code=500, detail=f"QMP loadvm failed: {qmp_res['error']}")
    else:
        if not os.path.exists(disk_path):
            raise HTTPException(status_code=400, detail="Primary disk not found.")
        qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
        try:
            await asyncio.to_thread(
                subprocess.run,
                [qemu_img, "snapshot", "-a", name, disk_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=15.0,
            )
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"qemu-img revert failed: {e.stderr or e}") from e

    add_event("info", "VM Snapshot Reverted", f"VM '{target_vm['name']}' reverted to snapshot '{name}'.")
    return {"success": True, "name": name, "vm_id": vm_id}


@router.delete(
    "/{vm_id}/snapshots/{snapshot_name}",
    dependencies=[
        Depends(require_scope("vms:manage", "system:config")),
        Depends(require_confirmation("storage.snapshot.delete")),
    ],
)
async def delete_vm_snapshot(vm_id: str, snapshot_name: str):
    """Deletes a named snapshot."""
    vms = vm_qemu._load_vms()
    target_vm = next((v for v in vms if v["id"] == vm_id), None)
    if not target_vm:
        raise HTTPException(status_code=404, detail="Virtual machine not found.")

    name = snapshot_name.strip()
    is_running = target_vm.get("state") == "running" and vm_qemu._is_qemu_process_alive(vm_id)
    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")

    if is_running:
        cmd_str = f"delvm {name}"
        qmp_res = await asyncio.to_thread(
            vm_qemu._qmp_command, vm_id, "human-monitor-command", {"command-line": cmd_str}, 10.0
        )
        if "error" in qmp_res:
            logger.warning(f"QMP delvm warning: {qmp_res['error']}")
    else:
        if os.path.exists(disk_path):
            qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
            try:
                await asyncio.to_thread(
                    subprocess.run,
                    [qemu_img, "snapshot", "-d", name, disk_path],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15.0,
                )
            except Exception as e:
                logger.warning(f"qemu-img delete snapshot warning: {e}")

    meta = await asyncio.to_thread(_get_vm_snapshots_metadata, vm_id)
    if name in meta:
        del meta[name]
        await asyncio.to_thread(_save_vm_snapshots_metadata, vm_id, meta)

    add_event("info", "VM Snapshot Deleted", f"Snapshot '{name}' deleted for VM '{target_vm['name']}'.")
    return {"success": True, "name": name, "vm_id": vm_id}


class VmBackupRequest(BaseModel):
    reason: str = Field("on-demand", description="'on-demand', 'scheduled', or 'pre-upgrade'")
    custom_name: str | None = Field(None, description="Optional custom name for the backup archive")


@router.post(
    "/{vm_id}/backup",
    dependencies=[Depends(require_scope("vms:manage", "system:config"))],
)
async def backup_virtual_machine(vm_id: str, req: VmBackupRequest | None = None):
    """Takes a full hyper-backup of VM configuration and virtual disks."""
    from backend.services.app_backup import create_vm_backup

    reason = req.reason if req else "on-demand"
    custom_name = req.custom_name if req else None
    try:
        record = await asyncio.to_thread(create_vm_backup, vm_id, reason=reason, custom_name=custom_name)
        return {"status": "ok", "backup": record}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"[VM Backup] Backup failed for {vm_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/{vm_id}/backups",
    dependencies=[Depends(require_scope("system:view", "storage:read"))],
)
async def list_virtual_machine_backups(vm_id: str):
    """Lists saved hyper-backup archives for target VM."""
    from backend.services.app_backup import list_vm_backups

    try:
        backups = await asyncio.to_thread(list_vm_backups, vm_id)
        return {"status": "ok", "vm_id": vm_id, "backups": backups}
    except Exception as e:
        logger.error(f"[VM Backup] Failed listing backups for {vm_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
