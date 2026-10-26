"""FygoOS: observed (Btrfs).

Part of the storage abstraction layer (backend/hardware/pal); split out of pal_storage.py (ARC-5)."""

import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import time
from abc import ABC, abstractmethod
from enum import Enum, StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, POOL_PATH, logger
from backend.fsutil import atomic_write_json
from backend.hardware.pal import base as pal_base
from backend.hardware.pal.base import (
    NetworkShare,
    PlatformCapabilities,
    PlatformType,
    StoragePool,
    btrfs_is_redundant,
)
from backend.hardware.pal.observer import ObserverStorageAdapter
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class FygoOSStorageAdapter(ObserverStorageAdapter):
    """
    FygoOS Storage Platform Adapter.
    Operates in Observer Mode. FygoOS authoritatively manages system volumes,
    media directories, and external drives.
    """

    def get_platform_type(self) -> PlatformType:
        return PlatformType.FYGOOS

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.FYGOOS,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=False,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["btrfs", "ext4", "f2fs"],
            description="Observer Mode: FygoOS host detected. Storage pools, external drives, and media directories are authoritatively managed by FygoOS. Telemetry and capacity auditing enabled.",
        )

    def is_storage_busy(self) -> bool:
        return False

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        return {
            "platform": "fygoos",
            "pool_id": pool_id,
            "action": action,
            "status": "monitoring",
            "message": "FygoOS manages volume integrity authoritatively.",
        }

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        mounts = self._parse_mounts()
        hal_disks = self._discover_hal_disks()

        storage_roots = ["/media", "/mnt/storage", "/storage", "/volume1"]
        checked_mounts = set()

        for m in mounts:
            mp = m.get("mountpoint", "")
            fstype = m.get("fstype", "")
            if fstype in ("ext4", "btrfs", "f2fs", "xfs"):
                if any(mp.startswith(r) for r in storage_roots) or mp in storage_roots:
                    try:
                        u = shutil.disk_usage(mp)
                        tot, usd, fre = u.total, u.used, u.free
                    except Exception:
                        continue
                    if tot == 0:
                        continue
                    pct = round(usd / tot * 100, 1)
                    checked_mounts.add(mp)
                    p_id = os.path.basename(mp) or "fygoos_storage"
                    # protected only when the Btrfs profile keeps copies on other disks
                    profiles = pal_base.btrfs_data_profiles(m.get("device", "")) if fstype == "btrfs" else []
                    redundant = btrfs_is_redundant(profiles)
                    pools.append(
                        StoragePool(
                            id=p_id,
                            name=f"{p_id} (FygoOS Storage Volume)",
                            pool_type="btrfs_raid" if redundant else "single",
                            fs_type=fstype,
                            fs_profile="+".join(profiles) or "single",
                            status="HEALTHY",
                            mountpoint=mp,
                            total_bytes=tot,
                            used_bytes=usd,
                            free_bytes=fre,
                            used_pct=pct,
                            members=hal_disks,
                            parity_protected=redundant,
                        )
                    )

        if not pools:
            cand = self._pool_path if os.path.exists(self._pool_path) else "/"
            try:
                u = shutil.disk_usage(cand)
                tot, usd, fre = u.total, u.used, u.free
            except Exception:
                tot, usd, fre = 0, 0, 0
            pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
            pools.append(
                StoragePool(
                    id="fygoos_main",
                    name="FygoOS Primary Storage",
                    pool_type="single",
                    fs_type="ext4",
                    status="HEALTHY",
                    mountpoint=cand,
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=hal_disks,
                    parity_protected=False,
                )
            )

        return pools

    def list_shares(self) -> list[NetworkShare]:
        shares = self._parse_smb_conf()
        if not shares:
            shares = self._discover_shares_from_dirs(["/media", "/mnt/storage", self._pool_path])
        return shares
