"""Observer mode: hosts whose storage another system manages (the base for appliance OSes).

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
    PlatformCapabilityError,
    PlatformType,
    StoragePlatformAdapter,
    StoragePool,
    _parse_ini_sections,
)
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class ObserverStorageAdapter(StoragePlatformAdapter):
    """
    Base class for all non-intrusive Observer Mode storage adapters (FygoOS, ZettOS, UGOS, Synology DSM, QTS, etc.).
    Guarantees strict read-only auditing and raises PlatformCapabilityError on all mutating operations.
    """

    def __init__(self, pool_path: str | None = None):
        self._pool_path = pool_path or pal_base.POOL_PATH or "/mnt/storage"

    def create_pool(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: {plat} authoritatively manages storage pools and RAID arrays. "
            "Provisioning pools from container is prohibited to prevent volume corruption."
        )

    def destroy_pool(self, pool_id: str, *args: Any, **kwargs: Any) -> Any:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(f"Observer mode active: Destroying pools is prohibited on {plat} host.")

    def create_share(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: Network shares on {plat} must be configured via host OS management."
        )

    def delete_share(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: Deleting network shares on {plat} must be performed via host OS."
        )

    def rename_pool(self, pool_id: str, new_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: Storage pool identifiers on {plat} are managed authoritatively by host OS."
        )

    def create_snapshot(
        self,
        pool_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: Filesystem snapshots on {plat} are managed authoritatively by host OS."
        )

    def list_snapshots(self, pool_id: str) -> list[dict[str, Any]]:
        return []

    def delete_snapshot(
        self,
        pool_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: Snapshot deletion on {plat} must be performed via host OS."
        )

    def restore_snapshot(self, pool_id: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(
            f"Observer mode active: Snapshot restoration on {plat} must be performed via host OS."
        )

    def export_pool(self, pool_id: str, force: bool = False) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(f"Observer mode active: Pool detachment on {plat} must be performed via host OS.")

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: str | None = None) -> dict[str, Any]:
        plat = self.get_platform_type().value
        raise PlatformCapabilityError(f"Observer mode active: Pool import on {plat} must be performed via host OS.")

    def discover_external_pools(self) -> list[dict[str, Any]]:
        return []

    def get_pool_path(self, pool_id: str) -> str:
        if not pool_id or pool_id in ("default_pool", "default"):
            return self._pool_path
        cand = os.path.join(self._pool_path, pool_id)
        return cand if os.path.exists(cand) else self._pool_path

    def _parse_smb_conf(self) -> list[NetworkShare]:
        """Parses Samba configuration files to identify host-exported network shares."""
        shares: list[NetworkShare] = []
        target_conf = next((c for c in pal_base.SMB_CONF_PATHS if os.path.isfile(c)), None)
        if not target_conf:
            return shares

        try:
            sections = _parse_ini_sections(target_conf)
            for sec_name, meta in sections.items():
                if sec_name.lower() in ("global", "homes", "printers", "print$"):
                    continue
                share_path = meta.get("path", "")
                if not share_path:
                    continue

                try:
                    u = shutil.disk_usage(share_path if os.path.exists(share_path) else "/")
                    tot, usd, fre = u.total, u.used, u.free
                except Exception:
                    tot, usd, fre = 0, 0, 0
                pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

                comment = meta.get("comment", "")
                guest_ok = meta.get("guest ok", meta.get("public", "no")).lower() in ("yes", "true", "1")

                shares.append(
                    NetworkShare(
                        name=sec_name,
                        comment=comment,
                        security="public" if guest_ok else "private",
                        export_smb=True,
                        export_nfs=False,
                        export_webdav=True,
                        mountpoint=share_path,
                        used_bytes=usd,
                        free_bytes=fre,
                        total_bytes=tot,
                        used_pct=pct,
                    )
                )
        except Exception as e:
            logger.debug(f"[PAL] Error reading smb.conf from {target_conf}: {e}")
        return shares

    def _discover_shares_from_dirs(self, base_dirs: list[str]) -> list[NetworkShare]:
        """Discovers user shares by inspecting subdirectories of candidate storage roots."""
        shares: list[NetworkShare] = []
        seen_names = set()
        for b in base_dirs:
            if not os.path.isdir(b):
                continue
            try:
                for entry in sorted(os.listdir(b)):
                    if entry.startswith(".") or entry in seen_names:
                        continue
                    full_p = os.path.join(b, entry)
                    if os.path.isdir(full_p):
                        seen_names.add(entry)
                        try:
                            u = shutil.disk_usage(full_p)
                            tot, usd, fre = u.total, u.used, u.free
                        except Exception:
                            tot, usd, fre = 0, 0, 0
                        pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                        shares.append(
                            NetworkShare(
                                name=entry,
                                comment=f"Share on {b}",
                                security="public",
                                export_smb=True,
                                export_nfs=False,
                                export_webdav=True,
                                mountpoint=full_p,
                                used_bytes=usd,
                                free_bytes=fre,
                                total_bytes=tot,
                                used_pct=pct,
                            )
                        )
            except Exception as e:
                logger.debug(f"[PAL] Error scanning storage directory {b}: {e}")
        return shares


class GenericObserverStorageAdapter(ObserverStorageAdapter):
    """
    Generic Observer Storage Platform Adapter.
    Operates in 100% non-intrusive Observer Mode on any Linux NAS OS (Synology DSM,
    QNAP QTS, Asustor ADM, CasaOS, or unprivileged bare-metal host).
    Strictly forbids block mutations while capturing non-intrusive pool and share telemetry.
    """

    def get_platform_type(self) -> PlatformType:
        return PlatformType.GENERIC_OBSERVER

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.GENERIC_OBSERVER,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=False,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["btrfs", "ext4", "xfs", "zfs"],
            description="Observer Mode: Non-intrusive telemetry mode active. Storage pools and file shares are authoritatively managed by host OS. Block-level modifications are strictly disabled.",
        )

    def is_storage_busy(self) -> bool:
        mdstats = self._parse_mdstat()
        return any(md_info.get("sync_action") for md_info in mdstats.values())

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        return {
            "platform": "generic_observer",
            "pool_id": pool_id,
            "action": action,
            "status": "monitoring",
            "message": "Host OS authoritatively manages storage scrub and parity verification.",
        }

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        mounts = self._parse_mounts()
        hal_disks = self._discover_hal_disks()

        for m in mounts:
            mp = m.get("mountpoint", "")
            fstype = m.get("fstype", "")
            if fstype not in ("ext4", "btrfs", "xfs", "zfs"):
                continue
            try:
                u = shutil.disk_usage(mp)
                tot, usd, fre = u.total, u.used, u.free
            except Exception:
                continue
            if tot == 0:
                continue
            pct = round(usd / tot * 100, 1)

            pool_id = os.path.basename(mp) or "storage_root"
            pools.append(
                StoragePool(
                    id=pool_id,
                    name=f"{pool_id} ({fstype.upper()} Volume)",
                    pool_type="single",
                    fs_type=fstype,
                    fs_profile="single",
                    status="HEALTHY",
                    mountpoint=mp,
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=hal_disks,
                    parity_protected=False,
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
                    id="host_storage",
                    name="Host Storage Volume",
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
            shares = self._discover_shares_from_dirs([self._pool_path, "/mnt", "/media"])
        return shares
