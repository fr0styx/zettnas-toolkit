"""UGOS (UGREEN): observed.

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
from backend.hardware.pal.base import (
    NetworkShare,
    PlatformCapabilities,
    PlatformType,
    PoolMember,
    StoragePool,
)
from backend.hardware.pal.observer import ObserverStorageAdapter
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class UgosStorageAdapter(ObserverStorageAdapter):
    """
    UGOS (UGREEN NAS OS) Storage Platform Adapter.
    Operates in Observer Mode. UGOS authoritatively manages mdadm RAID volumes,
    LVM thin-pools, and user shares under /volume1, /volume2, etc.
    """

    def get_platform_type(self) -> PlatformType:
        return PlatformType.UGOS

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.UGOS,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=True,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["btrfs", "ext4"],
            description="Observer Mode: UGOS (UGREEN NAS OS) host detected. Storage pools, mdadm RAID groups, and LVM volumes are authoritatively managed by UGOS. Telemetry and RAID scrub monitoring enabled.",
        )

    def is_storage_busy(self) -> bool:
        mdstats = self._parse_mdstat()
        return any(md_info.get("sync_action") for md_info in mdstats.values())

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        mdstats = self._parse_mdstat()
        busy = False
        action_name = "idle"
        pct = 0.0
        for _md_dev, info in mdstats.items():
            if info.get("sync_action"):
                busy = True
                action_name = info["sync_action"]
                pct = info.get("progress_pct", 0.0)
                break

        return {
            "platform": "ugos",
            "pool_id": pool_id,
            "action": action,
            "status": "active" if busy else "idle",
            "sync_action": action_name,
            "progress_pct": pct,
            "message": "UGOS manages RAID resync and scrub authoritatively via kernel md/btrfs.",
        }

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        mdstats = self._parse_mdstat()
        mounts = self._parse_mounts()
        hal_disks = {d.name: d for d in self._discover_hal_disks()}

        volume_paths = []
        for i in range(1, 10):
            for base in ["", "/host", "/mnt"]:
                cand = f"{base}/volume{i}"
                if os.path.isdir(cand) and cand not in volume_paths:
                    volume_paths.append(cand)

        for m in mounts:
            mp = m.get("mountpoint", "")
            if re.match(r"^(/host|/mnt)?/volume\d+", mp) and mp not in volume_paths:
                volume_paths.append(mp)

        if not volume_paths:
            volume_paths = [self._pool_path]

        for v_path in sorted(volume_paths):
            if not os.path.exists(v_path):
                continue
            vol_name = os.path.basename(v_path)
            try:
                u = shutil.disk_usage(v_path)
                tot, usd, fre = u.total, u.used, u.free
            except Exception:
                tot, usd, fre = 0, 0, 0
            pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

            fs_type = "btrfs"
            for m in mounts:
                if m.get("mountpoint") == v_path:
                    fs_type = m.get("fstype", "btrfs")
                    break

            members: list[PoolMember] = []
            raid_profile = "raid5"
            status = "HEALTHY"

            for _md_dev, info in mdstats.items():
                if info.get("degraded"):
                    status = "DEGRADED"
                raid_profile = info.get("level", raid_profile)
                for member_name in info.get("members", []):
                    clean_name = re.sub(r"\d+$", "", member_name)
                    if clean_name in hal_disks:
                        members.append(hal_disks[clean_name])
                    else:
                        members.append(
                            PoolMember(
                                name=member_name,
                                device=clean_name,
                                id=member_name,
                                type="Data",
                                role="data",
                                status="OK" if status == "HEALTHY" else "DEGRADED",
                            )
                        )

            if not members:
                members = list(hal_disks.values())

            parity_protected = raid_profile in ("raid1", "raid5", "raid6", "raid10")

            pools.append(
                StoragePool(
                    id=vol_name,
                    name=f"{vol_name.capitalize()} (UGOS Storage Pool)",
                    pool_type="mdadm_btrfs" if fs_type == "btrfs" else "mdadm_raid",
                    fs_type=fs_type,
                    fs_profile=raid_profile,
                    status=status,
                    mountpoint=v_path,
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=members,
                    parity_protected=parity_protected,
                )
            )

        return pools

    def list_shares(self) -> list[NetworkShare]:
        shares = self._parse_smb_conf()
        if not shares:
            vol_dirs = [f"/volume{i}" for i in range(1, 10)] + [f"/host/volume{i}" for i in range(1, 10)]
            existing_vols = [v for v in vol_dirs if os.path.isdir(v)]
            shares = self._discover_shares_from_dirs(existing_vols or [self._pool_path])
        return shares
