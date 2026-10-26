"""
ZettNAS Toolkit - Platform Abstraction Layer (PAL)
Universal Storage Subsystem Interface for Appliance & Generic Linux Hosts.
Provides hardware- and OS-agnostic disk, pool, and network share abstractions.

The code lives in the backend/hardware/pal package, one module per platform (ARC-5). This
module keeps the import path everyone uses, re-exports those names and picks the adapter.
Host paths and helpers that tests patch live in backend.hardware.pal.base (pal_storage.base).
"""

# The standard modules the old single file imported: tests patch them through this module
# (pal_storage.subprocess.run, pal_storage.os.path.join, pal_storage.shutil.disk_usage).
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import time

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, POOL_PATH, logger
from backend.hardware.pal import base
from backend.hardware.pal.base import (
    BTRFS_REDUNDANT,
    SMB_CONF_PATHS,
    NetworkShare,
    PlatformCapabilities,
    PlatformCapabilityError,
    PlatformType,
    PoolMember,
    StoragePlatformAdapter,
    StoragePool,
    _parse_ini_sections,
    _whole_disk,
    btrfs_data_profiles,
    btrfs_is_redundant,
)
from backend.hardware.pal.detect import StoragePlatformDetector
from backend.hardware.pal.fygoos import FygoOSStorageAdapter
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter
from backend.hardware.pal.observer import GenericObserverStorageAdapter, ObserverStorageAdapter
from backend.hardware.pal.proxmox import ProxmoxStorageAdapter
from backend.hardware.pal.truenas import TrueNASStorageAdapter
from backend.hardware.pal.ugos import UgosStorageAdapter
from backend.hardware.pal.unraid import UnraidStorageAdapter
from backend.hardware.pal.zettos import ZettOSStorageAdapter
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status

__all__ = [
    "json",
    "os",
    "re",
    "shutil",
    "struct",
    "subprocess",
    "time",
    "BTRFS_REDUNDANT",
    "FygoOSStorageAdapter",
    "GenericLinuxStorageAdapter",
    "GenericObserverStorageAdapter",
    "NetworkShare",
    "ObserverStorageAdapter",
    "PlatformCapabilities",
    "PlatformCapabilityError",
    "PlatformType",
    "PoolMember",
    "ProxmoxStorageAdapter",
    "SMB_CONF_PATHS",
    "StoragePlatformAdapter",
    "StoragePlatformDetector",
    "StoragePool",
    "TrueNASStorageAdapter",
    "UgosStorageAdapter",
    "UnraidStorageAdapter",
    "ZettOSStorageAdapter",
    "_parse_ini_sections",
    "_whole_disk",
    "btrfs_data_profiles",
    "btrfs_is_redundant",
    "HOST_DEV",
    "HOST_PROC",
    "HOST_SYS",
    "POOL_PATH",
    "_find_emhttp_dir",
    "base",
    "read_unraid_status",
    "sqlite3",
]


_CACHED_ADAPTER: StoragePlatformAdapter | None = None


def get_storage_platform(force_refresh: bool = False) -> StoragePlatformAdapter:
    """Returns singleton platform adapter based on detected host environment."""
    global _CACHED_ADAPTER
    if _CACHED_ADAPTER is not None and not force_refresh:
        return _CACHED_ADAPTER

    platform_type = StoragePlatformDetector.detect()
    logger.info(f"[PAL] Storage platform detected: {platform_type.value}")

    if platform_type == PlatformType.UNRAID:
        _CACHED_ADAPTER = UnraidStorageAdapter()
    elif platform_type == PlatformType.TRUENAS:
        _CACHED_ADAPTER = TrueNASStorageAdapter()
    elif platform_type == PlatformType.PROXMOX:
        _CACHED_ADAPTER = ProxmoxStorageAdapter()
    elif platform_type == PlatformType.FYGOOS:
        _CACHED_ADAPTER = FygoOSStorageAdapter()
    elif platform_type == PlatformType.ZETTOS:
        _CACHED_ADAPTER = ZettOSStorageAdapter()
    elif platform_type == PlatformType.UGOS:
        _CACHED_ADAPTER = UgosStorageAdapter()
    elif platform_type == PlatformType.GENERIC_OBSERVER:
        _CACHED_ADAPTER = GenericObserverStorageAdapter()
    else:
        _CACHED_ADAPTER = GenericLinuxStorageAdapter()

    return _CACHED_ADAPTER
