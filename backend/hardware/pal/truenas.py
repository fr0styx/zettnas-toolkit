"""TrueNAS: observed through its API.

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
    PlatformCapabilityError,
    PlatformType,
    StoragePool,
)
from backend.hardware.pal.observer import ObserverStorageAdapter
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class TrueNASStorageAdapter(ObserverStorageAdapter):
    """
    TrueNAS SCALE Storage Platform Adapter.
    Operates in Observer Mode. TrueNAS Middleware authoritatively manages ZFS pools,
    datasets, permissions, and NFS/SMB shares.
    """

    def get_platform_type(self) -> PlatformType:
        return PlatformType.TRUENAS

    def create_snapshot(self, pool_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """With TRUENAS_URL and TRUENAS_API_KEY set, snapshots go through the TrueNAS API (D5)."""
        from backend.services import truenas_api

        if not truenas_api.configured():
            return super().create_snapshot(pool_id, *args, **kwargs)
        name = kwargs.get("snapshot_name") or (args[1] if len(args) > 1 else "") or "zettnas"
        return truenas_api.create_snapshot(pool_id, name, recursive=True)

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.TRUENAS,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=True,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["zfs"],
            description="Observer Mode: TrueNAS SCALE host detected. ZFS pools, datasets, and shares are managed by TrueNAS Middleware. Telemetry and scrub monitoring enabled.",
        )

    def create_pool(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        raise PlatformCapabilityError(
            "Pool creation is prohibited on TrueNAS SCALE in observer mode. Use TrueNAS Web UI to provision ZFS pools."
        )

    def destroy_pool(self, pool_id: str, *args: Any, **kwargs: Any) -> Any:
        raise PlatformCapabilityError(
            "Pool destruction is prohibited on TrueNAS SCALE in observer mode. Use TrueNAS Web UI to manage ZFS pools."
        )

    _busy_cache_ts: float = 0.0
    _busy_cache_val: bool = False

    def is_storage_busy(self) -> bool:
        if os.environ.get("TESTING") == "1" or os.environ.get("ZETTNAS_TEST_MODE") == "1":
            return self._check_is_storage_busy_uncached()
        now = time.time()
        if now - getattr(self, "_busy_cache_ts", 0.0) < 10.0:
            return getattr(self, "_busy_cache_val", False)
        val = self._check_is_storage_busy_uncached()
        self._busy_cache_ts = now
        self._busy_cache_val = val
        return val

    def _check_is_storage_busy_uncached(self) -> bool:
        code, out, _ = self._run_cmd(["zpool", "status"])
        return code == 0 and ("scrub in progress" in out.lower() or "resilver in progress" in out.lower())

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        zp = pool_id if (pool_id and pool_id != "default_pool") else "boot-pool"
        if action == "start":
            code, out, err = self._run_cmd(["zpool", "scrub", zp])
            return {
                "platform": "truenas",
                "pool_id": pool_id,
                "action": action,
                "status": "started" if code == 0 else "error",
                "output": out or err,
            }
        elif action == "cancel":
            code, out, err = self._run_cmd(["zpool", "scrub", "-s", zp])
            return {
                "platform": "truenas",
                "pool_id": pool_id,
                "action": action,
                "status": "cancelled" if code == 0 else "error",
                "output": out or err,
            }
        else:
            code, out, err = self._run_cmd(["zpool", "status", zp])
            return {
                "platform": "truenas",
                "pool_id": pool_id,
                "action": "status",
                "status": "active" if "scrub in progress" in out.lower() else "idle",
                "raw": out or err,
            }

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        code, zout, _ = self._run_cmd(["zpool", "list", "-Hp", "-o", "name,size,alloc,free,health"])
        if code == 0 and zout.strip():
            hal_disks = self._discover_hal_disks()
            for line in zout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 5:
                    zp_name, zp_size, zp_alloc, zp_free, zp_health = (
                        parts[0].strip(),
                        parts[1].strip(),
                        parts[2].strip(),
                        parts[3].strip(),
                        parts[4].strip(),
                    )
                    tot = int(zp_size) if zp_size.isdigit() else 0
                    usd = int(zp_alloc) if zp_alloc.isdigit() else 0
                    fre = int(zp_free) if zp_free.isdigit() else 0
                    pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                    pools.append(
                        StoragePool(
                            id=zp_name,
                            name=f"{zp_name} (ZFS Pool)",
                            pool_type="zfs_pool",
                            fs_type="zfs",
                            status="HEALTHY" if zp_health == "ONLINE" else zp_health,
                            mountpoint=f"/mnt/{zp_name}",
                            total_bytes=tot,
                            used_bytes=usd,
                            free_bytes=fre,
                            used_pct=pct,
                            members=hal_disks,
                            parity_protected=True,
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
                    id="boot-pool",
                    name="boot-pool",
                    pool_type="zfs_pool",
                    fs_type="zfs",
                    status="HEALTHY",
                    mountpoint=cand,
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=self._discover_hal_disks(),
                    parity_protected=True,
                )
            )
        return pools

    def list_shares(self) -> list[NetworkShare]:
        shares = self._parse_smb_conf()
        if not shares:
            shares = self._discover_shares_from_dirs(["/mnt", self._pool_path])
        return shares
