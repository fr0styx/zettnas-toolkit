"""
VM settings storage and input confinement (paths and options that reach QEMU),
plus the shared QEMU process state.

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
from backend.services.vm_engine import QmpEngine
from backend.state import Z_STATE, add_event

# ---- QEMU input confinement (SEC-07) ----
# Paths and options from VM settings end up inside QEMU option strings, where a comma
# starts a new option. Disks, ISOs and host shares must be regular files or folders
# inside the VM and storage roots; host block devices and the app's data folder are out.
_QEMU_UNSAFE = re.compile(r"[,\r\n\x00]")


_DISK_BUSES = {"virtio", "sata", "nvme", "ide", "scsi"}


_DISK_FORMATS = {"qcow2", "raw"}


def _vm_disk_roots() -> list[str]:
    from backend.api.fs import ALLOWED_BROWSE_ROOTS

    roots = [os.path.join(DATA_DIR, "vms")] + [r for r in ALLOWED_BROWSE_ROOTS if r]
    return [os.path.realpath(r) for r in roots]


def _vm_iso_roots() -> list[str]:
    return [os.path.realpath(r) for r in [VM_ISO_DIR, *(_vm_disk_roots())] if r]


def _vm_share_roots() -> list[str]:
    from backend.api.fs import ALLOWED_BROWSE_ROOTS

    data = os.path.realpath(DATA_DIR)
    return [os.path.realpath(r) for r in ALLOWED_BROWSE_ROOTS if r and os.path.realpath(r) != data]


def _confined(path: Any, roots: list[str], want: str = "file") -> str | None:
    """realpath of `path` if it is safe to give QEMU, else None."""
    if not isinstance(path, str) or not path.strip() or _QEMU_UNSAFE.search(path):
        return None
    real = os.path.realpath(path.strip())
    if _QEMU_UNSAFE.search(real):
        return None
    if not any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots):
        return None
    data = os.path.realpath(DATA_DIR)
    vms_dir = os.path.join(data, "vms")
    if (real == data or real.startswith(data + "/")) and not (real == vms_dir or real.startswith(vms_dir + "/")):
        return None
    if os.path.exists(real):
        if want == "file" and not os.path.isfile(real):
            return None
        if want == "dir" and not os.path.isdir(real):
            return None
    return real


def _validate_vm_inputs(
    secondary_disks: list[dict[str, Any]] | None = None,
    iso_path: str | None = None,
    host_shares: list[dict[str, Any]] | None = None,
) -> None:
    """Refuses VM settings that would reach host devices or inject QEMU options (400)."""
    for i, d in enumerate(secondary_disks or []):
        if not isinstance(d, dict):
            raise HTTPException(status_code=400, detail=f"Secondary disk {i + 1} is not valid.")
        if d.get("path") and not _confined(d.get("path"), _vm_disk_roots(), "file"):
            raise HTTPException(
                status_code=400,
                detail=f"Secondary disk {i + 1}: use an image file inside the VM or storage folders (not a host device).",
            )
        if str(d.get("bus", "virtio")) not in _DISK_BUSES:
            raise HTTPException(status_code=400, detail=f"Secondary disk {i + 1}: unsupported bus.")
        if d.get("format") and str(d.get("format")) not in _DISK_FORMATS:
            raise HTTPException(status_code=400, detail=f"Secondary disk {i + 1}: format must be qcow2 or raw.")
        if d.get("name") and not re.match(r"^[A-Za-z0-9_-]{1,64}$", str(d.get("name"))):
            raise HTTPException(status_code=400, detail=f"Secondary disk {i + 1}: invalid name.")
    if iso_path and iso_path.strip() and not _confined(iso_path, _vm_iso_roots(), "file"):
        raise HTTPException(status_code=400, detail="The ISO must be a file in the ISO or storage folders.")
    for i, sh in enumerate(host_shares or []):
        if not isinstance(sh, dict) or not _confined(sh.get("host_path"), _vm_share_roots(), "dir"):
            raise HTTPException(status_code=400, detail=f"Host share {i + 1}: choose a folder inside the storage pool.")
        if sh.get("mode", "rw") not in ("ro", "rw"):
            raise HTTPException(status_code=400, detail=f"Host share {i + 1}: mode must be ro or rw.")


VMS_CONFIG_FILE = os.path.join(DATA_DIR, "vms.json")


KVM_GET_API_VERSION = 0xAE00


# In-memory transient caches for download jobs and web console tickets
_DOWNLOAD_TASKS: dict[str, dict[str, Any]] = {}


_ABORT_DOWNLOAD_TASKS: set = set()


_CONSOLE_TICKETS: dict[str, dict[str, Any]] = {}


# Curated Official Operating System ISO Catalog
OFFICIAL_ISO_CATALOG: list[dict[str, Any]] = [
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


_RUNNING_QEMU_PROCS: dict[str, dict[str, Any]] = {}


_LAST_QEMU_ERRORS: dict[str, str] = {}
