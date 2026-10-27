"""Unraid: the array, pools and shares from emhttp's state files.

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
    PoolMember,
    StoragePlatformAdapter,
    StoragePool,
    _parse_ini_sections,
)
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class UnraidStorageAdapter(StoragePlatformAdapter):
    """
    Unraid OS Storage Platform Adapter.
    Operates in 100% Observer / Companion Mode.
    Audits array status, parity protection, cache pools, and user shares via emhttp state files.
    Strictly forbids array tampering or destructive block operations.
    """

    def __init__(self):
        self._emhttp_dir = pal_base._find_emhttp_dir()

    def get_platform_type(self) -> PlatformType:
        return PlatformType.UNRAID

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.UNRAID,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=True,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["unraid", "btrfs", "zfs", "xfs"],
            description="Observer Mode: Unraid OS authoritatively manages array disks and shares. Modifying pools from container is prohibited to protect parity.",
        )

    def is_storage_busy(self) -> bool:
        status = read_unraid_status()
        resync = status.get("parity_check", {}).get("active", False)
        mover = status.get("mover", {}).get("active", False)
        return bool(resync or mover)

    def scrub_result(self, pool: StoragePool) -> dict[str, Any] | None:
        """The array's last parity check (Unraid keeps it in var.ini); other pools as usual."""
        if pool.id != "unraid_array":
            return super().scrub_result(pool)
        last = (read_unraid_status() or {}).get("last_parity_check") or {}
        if not last.get("finished_at"):
            return {"state": "never", "errors": 0, "finished_at": None}
        return {
            "state": "finished" if last.get("exit") == 0 else "canceled",
            "errors": int(last.get("errors") or 0),
            "finished_at": float(last["finished_at"]),
        }

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        status = read_unraid_status(force=True)
        parity_check = status.get("parity_check", {})
        return {
            "platform": "unraid",
            "pool_id": pool_id,
            "action": action,
            "status": "monitoring",
            "active": parity_check.get("active", False),
            "progress_pct": parity_check.get("progress_pct", 0.0),
            "errors": parity_check.get("errors", 0),
            "message": "Unraid manages array parity checks via emhttp. Use Unraid Dashboard or API to start/stop.",
        }

    def list_pools(self) -> list[StoragePool]:
        emhttp_dir = self._emhttp_dir or pal_base._find_emhttp_dir()
        if not emhttp_dir:
            return self._fallback_pools()

        disks_file = os.path.join(emhttp_dir, "disks.ini")
        disks_data = _parse_ini_sections(disks_file)
        if not disks_data:
            return self._fallback_pools()

        pools: list[StoragePool] = []
        array_members: list[PoolMember] = []
        cache_pools: dict[str, list[PoolMember]] = {}
        cache_pool_meta: dict[str, dict[str, Any]] = {}
        boot_members: list[PoolMember] = []
        boot_meta: dict[str, Any] = {}

        array_total_bytes = 0
        array_used_bytes = 0
        array_free_bytes = 0
        has_parity = False
        array_fs_types = set()

        for sec_name, d in disks_data.items():
            device = d.get("device", "").strip()
            size_raw = d.get("size", "0")
            try:
                size_kib = int(size_raw)
            except ValueError:
                size_kib = 0

            # Skip not present disks
            if not device and size_kib == 0:
                continue

            size_bytes = size_kib * 1024
            dtype = d.get("type", "Data").strip()
            raw_temp = d.get("temp", "*")
            temp_c = int(raw_temp) if raw_temp.isdigit() else None
            spundown = d.get("spundown", "0") == "1"
            status_str = d.get("status", "DISK_OK")
            rotational = d.get("rotational", "1") == "1"
            ident = d.get("id", "")

            reads = int(d.get("numReads", 0)) if str(d.get("numReads", 0)).isdigit() else 0
            writes = int(d.get("numWrites", 0)) if str(d.get("numWrites", 0)).isdigit() else 0
            errors = int(d.get("numErrors", 0)) if str(d.get("numErrors", 0)).isdigit() else 0

            member = PoolMember(
                name=sec_name,
                device=device,
                id=ident,
                type=dtype,
                role=dtype.lower(),
                size_bytes=size_bytes,
                status="STANDBY" if spundown else ("OK" if status_str == "DISK_OK" else status_str),
                rotational=rotational,
                spundown=spundown,
                temp_c=temp_c,
                num_reads=reads,
                num_writes=writes,
                num_errors=errors,
            )

            if dtype == "Parity":
                has_parity = True
                member.role = "parity"
                array_members.append(member)
            elif dtype == "Data":
                member.role = "data"
                array_members.append(member)
                fs_used_kib = int(d.get("fsUsed", 0)) if str(d.get("fsUsed", 0)).isdigit() else 0
                fs_free_kib = int(d.get("fsFree", 0)) if str(d.get("fsFree", 0)).isdigit() else 0
                fs_size_kib = int(d.get("fsSize", 0)) if str(d.get("fsSize", 0)).isdigit() else 0

                array_used_bytes += fs_used_kib * 1024
                array_free_bytes += fs_free_kib * 1024
                array_total_bytes += fs_size_kib * 1024

                fs_type = d.get("fsType")
                if fs_type and fs_type != "auto":
                    array_fs_types.add(fs_type)
            elif dtype == "Cache":
                pool_key = d.get("nameOrig") or sec_name.rstrip("0123456789") or "cache"
                if pool_key not in cache_pools:
                    cache_pools[pool_key] = []
                    cache_pool_meta[pool_key] = {
                        "fs_type": d.get("fsType", "btrfs"),
                        "fs_profile": d.get("fsProfile", "single"),
                        "mountpoint": d.get("fsMountpoint", f"/mnt/{pool_key}"),
                        "fs_size": int(d.get("fsSize", 0)) if str(d.get("fsSize", 0)).isdigit() else 0,
                        "fs_used": int(d.get("fsUsed", 0)) if str(d.get("fsUsed", 0)).isdigit() else 0,
                        "fs_free": int(d.get("fsFree", 0)) if str(d.get("fsFree", 0)).isdigit() else 0,
                        "autotrim": d.get("autotrim", "off") == "on",
                        "status": "HEALTHY" if d.get("color", "").startswith("green") else "WARNING",
                    }
                member.role = "cache"
                cache_pools[pool_key].append(member)
            elif dtype in ("Boot", "Flash") or sec_name in ("flash", "boot"):
                member.role = "boot"
                boot_members.append(member)
                if not boot_meta:
                    boot_meta = {
                        "fs_type": d.get("fsType", "zfs"),
                        "mountpoint": d.get("fsMountpoint", "/boot"),
                        "fs_size": int(d.get("fsSize", 0)) if str(d.get("fsSize", 0)).isdigit() else 0,
                        "fs_used": int(d.get("fsUsed", 0)) if str(d.get("fsUsed", 0)).isdigit() else 0,
                        "fs_free": int(d.get("fsFree", 0)) if str(d.get("fsFree", 0)).isdigit() else 0,
                        "status": "HEALTHY" if d.get("color", "").startswith("green") else "OK",
                    }

        # 1. Main Array Pool
        unraid_stat = read_unraid_status()
        array_health = "HEALTHY" if unraid_stat.get("is_healthy", True) else "DEGRADED"
        if unraid_stat.get("parity_check", {}).get("active"):
            array_health = "SYNCING"

        used_pct = round(array_used_bytes / array_total_bytes * 100, 1) if array_total_bytes > 0 else 0.0
        primary_fs = ", ".join(sorted(array_fs_types)) if array_fs_types else "xfs"

        pools.append(
            StoragePool(
                id="unraid_array",
                name="Main Array",
                pool_type="unraid_array",
                fs_type=primary_fs,
                fs_profile=f"parity-{len([m for m in array_members if m.role == 'parity'])}" if has_parity else "jbod",
                status=array_health,
                mountpoint=pal_base.POOL_PATH or "/mnt/user",
                total_bytes=array_total_bytes,
                used_bytes=array_used_bytes,
                free_bytes=array_free_bytes,
                used_pct=used_pct,
                members=array_members,
                parity_protected=has_parity,
                autotrim=False,
                compression="off",
            )
        )

        # 2. Cache Pools (e.g. ark)
        for pool_key, members in cache_pools.items():
            meta = cache_pool_meta.get(pool_key, {})
            tot = meta.get("fs_size", 0) * 1024
            usd = meta.get("fs_used", 0) * 1024
            fre = meta.get("fs_free", 0) * 1024
            pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

            pools.append(
                StoragePool(
                    id=f"cache_{pool_key}",
                    name=f"{pool_key.upper()} (Cache Pool)",
                    pool_type="btrfs_raid" if "btrfs" in meta.get("fs_type", "") else "zfs_pool",
                    fs_type=meta.get("fs_type", "btrfs"),
                    fs_profile=meta.get("fs_profile", "raid1"),
                    status=meta.get("status", "HEALTHY"),
                    mountpoint=meta.get("mountpoint", f"/mnt/{pool_key}"),
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=members,
                    parity_protected=meta.get("fs_profile") in ("raid1", "raid10", "raid5", "raid6", "mirror"),
                    autotrim=meta.get("autotrim", False),
                    compression="off",
                )
            )

        # 3. Boot / Flash
        if boot_members:
            tot = boot_meta.get("fs_size", 0) * 1024
            usd = boot_meta.get("fs_used", 0) * 1024
            fre = boot_meta.get("fs_free", 0) * 1024
            pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

            pools.append(
                StoragePool(
                    id="boot_pool",
                    name="Boot Pool (Unraid OS)",
                    pool_type="zfs_pool" if "zfs" in boot_meta.get("fs_type", "") else "single",
                    fs_type=boot_meta.get("fs_type", "zfs"),
                    fs_profile="single",
                    status=boot_meta.get("status", "HEALTHY"),
                    mountpoint=boot_meta.get("mountpoint", "/boot"),
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=boot_members,
                    parity_protected=False,
                    autotrim=True,
                    compression="off",
                )
            )

        return pools

    def list_shares(self) -> list[NetworkShare]:
        emhttp_dir = self._emhttp_dir or pal_base._find_emhttp_dir()
        shares: list[NetworkShare] = []
        shares_data: dict[str, dict[str, str]] = {}
        sec_data: dict[str, dict[str, str]] = {}
        sec_nfs_data: dict[str, dict[str, str]] = {}

        if emhttp_dir:
            shares_data = _parse_ini_sections(os.path.join(emhttp_dir, "shares.ini"))
            sec_data = _parse_ini_sections(os.path.join(emhttp_dir, "sec.ini"))
            sec_nfs_data = _parse_ini_sections(os.path.join(emhttp_dir, "sec_nfs.ini"))

        # Fallback to /boot/config/shares/*.cfg if shares.ini is empty or absent
        if not shares_data:
            shares_cfg_candidates = [
                "/boot/config/shares",
                "/host/shares",
                "/host/boot/config/shares",
            ]
            cfg_dir = next((c for c in shares_cfg_candidates if os.path.isdir(c)), None)
            if cfg_dir:
                for fname in sorted(os.listdir(cfg_dir)):
                    if fname.endswith(".cfg"):
                        share_name = fname[:-4]
                        cfg_path = os.path.join(cfg_dir, fname)
                        try:
                            share_meta: dict[str, str] = {}
                            with open(cfg_path, encoding="utf-8", errors="replace") as f:
                                for line in f:
                                    line = line.strip()
                                    if "=" in line and not line.startswith("#"):
                                        k, v = line.split("=", 1)
                                        share_meta[k.strip()] = v.strip().strip('"').strip("'")
                            shares_data[share_name] = {
                                "name": share_name,
                                "comment": share_meta.get("shareComment", ""),
                                "useCache": share_meta.get("shareUseCache", "none"),
                                "cachePool": share_meta.get("shareCachePool", ""),
                                "allocator": share_meta.get("shareAllocator", "highwater"),
                                "cow": share_meta.get("shareCOW", "auto"),
                            }
                            sec_data[share_name] = {
                                "export": share_meta.get("shareExport", "-"),
                                "security": share_meta.get("shareSecurity", "public"),
                            }
                            sec_nfs_data[share_name] = {
                                "export": share_meta.get("shareExportNFS", "-"),
                            }
                        except Exception as e:
                            logger.debug(f"[PAL] Error reading cfg {cfg_path}: {e}")

        # Scan active storage pool path for folder mounts if no ini or cfg files
        base_pool_path = pal_base.POOL_PATH or "/mnt/user"
        if not shares_data and os.path.isdir(base_pool_path):
            try:
                for entry in sorted(os.listdir(base_pool_path)):
                    full_p = os.path.join(base_pool_path, entry)
                    if os.path.isdir(full_p) and not entry.startswith("."):
                        shares_data[entry] = {
                            "name": entry,
                            "comment": "User share",
                            "useCache": "none",
                        }
            except Exception as e:
                logger.debug(f"[PAL] Error listing {base_pool_path}: {e}")

        for name, meta in sorted(shares_data.items()):
            mount_path = os.path.join(base_pool_path, name)
            comment = meta.get("comment", "")
            use_cache = meta.get("useCache", "none")
            cache_pool = meta.get("cachePool") or None
            allocator = meta.get("allocator", "highwater")
            cow = meta.get("cow", "auto")

            # Determine disk usage in bytes
            free_raw = meta.get("free")
            used_raw = meta.get("used")
            if free_raw is not None and used_raw is not None and str(free_raw).isdigit() and str(used_raw).isdigit():
                free_bytes = int(free_raw) * 1024
                used_bytes = int(used_raw) * 1024
                total_bytes = free_bytes + used_bytes
            else:
                try:
                    u = shutil.disk_usage(mount_path if os.path.exists(mount_path) else base_pool_path)
                    total_bytes = u.total
                    free_bytes = u.free
                    used_bytes = u.used
                except Exception:
                    total_bytes, free_bytes, used_bytes = 0, 0, 0

            used_pct = round(used_bytes / total_bytes * 100, 1) if total_bytes > 0 else 0.0

            export_smb = sec_data.get(name, {}).get("export", meta.get("export", "e")) == "e"
            security = sec_data.get(name, {}).get("security", meta.get("security", "public"))
            export_nfs = sec_nfs_data.get(name, {}).get("export", "-") == "e"

            shares.append(
                NetworkShare(
                    name=name,
                    comment=comment,
                    security=security,
                    export_smb=export_smb,
                    export_nfs=export_nfs,
                    export_webdav=True,  # Universal WebDAV covers all mounted shares
                    cache_mode=use_cache,
                    cache_pool=cache_pool,
                    mountpoint=mount_path,
                    used_bytes=used_bytes,
                    free_bytes=free_bytes,
                    total_bytes=total_bytes,
                    used_pct=used_pct,
                    allocator=allocator,
                    cow=cow,
                )
            )

        return shares

    def _fallback_pools(self) -> list[StoragePool]:
        """Provides disk usage fallback when emhttp state is inaccessible."""
        total, used, free = 0, 0, 0
        try:
            u = shutil.disk_usage(pal_base.POOL_PATH or "/mnt/user")
            total, used, free = u.total, u.used, u.free
        except Exception:
            logger.debug(
                "backend.hardware.pal_storage.UnraidStorageAdapter._fallback_pools: ignored error", exc_info=True
            )
        pct = round(used / total * 100, 1) if total > 0 else 0.0
        return [
            StoragePool(
                id="unraid_array",
                name="Main Storage Pool",
                pool_type="unraid_array",
                fs_type="xfs",
                status="HEALTHY",
                mountpoint=pal_base.POOL_PATH or "/mnt/user",
                total_bytes=total,
                used_bytes=used,
                free_bytes=free,
                used_pct=pct,
                members=[],
                parity_protected=True,
            )
        ]

    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: list[str],
        mountpoint: str,
    ) -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Unraid OS authoritatively manages array disks and pools. "
            "Modifying pools from within container is prohibited to protect array parity."
        )

    def destroy_pool(self, pool_id: str) -> dict[str, Any]:
        raise PlatformCapabilityError("Observer mode active: Destroying pools is prohibited on Unraid appliance hosts.")

    def export_pool(self, pool_id: str, force: bool = False) -> dict[str, Any]:
        if pool_id in ("unraid_array", "default_pool", "flash"):
            raise PlatformCapabilityError(
                "Observer mode active: The primary Unraid array must be stopped via the Unraid WebGUI Main tab."
            )
        code, out, _ = self._run_cmd(["zpool", "status", pool_id])
        if code == 0:
            self._run_cmd(["sync"])
            exp_cmd = ["zpool", "export", "-f", pool_id] if force else ["zpool", "export", pool_id]
            c, o, err = self._run_cmd(exp_cmd)
            if c != 0:
                raise RuntimeError(f"Failed to export zpool '{pool_id}': {err or 'busy or in use'}")
            return {
                "status": "exported",
                "pool_id": pool_id,
                "fs_type": "zfs",
                "safe_to_disconnect": True,
                "message": f"External storage pool '{pool_id}' safely exported and flushed. Safe to disconnect cable.",
            }
        raise PlatformCapabilityError(f"Pool '{pool_id}' is part of Unraid array or cannot be detached.")

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: str | None = None) -> dict[str, Any]:
        if fs_type.lower() == "zfs":
            code, out, err = self._run_cmd(["zpool", "import", "-f", pool_id])
            if code != 0:
                raise RuntimeError(f"Failed to import zpool '{pool_id}': {err or out}")
            return {"status": "imported", "pool_id": pool_id, "fs_type": "zfs"}
        raise PlatformCapabilityError("Non-ZFS external pools on Unraid must be mounted via Unassigned Devices.")

    def discover_external_pools(self) -> list[dict[str, Any]]:
        discovered = []
        code, out, _ = self._run_cmd(["zpool", "import"])
        if code == 0 and out.strip():
            current_pool = {}
            for line in out.splitlines():
                line_str = line.strip()
                if line_str.startswith("pool:"):
                    if current_pool.get("pool_id"):
                        discovered.append(current_pool)
                    current_pool = {
                        "pool_id": line_str.split(":", 1)[1].strip(),
                        "fs_type": "zfs",
                        "status": "ONLINE",
                        "detachable": True,
                    }
                elif line_str.startswith("id:") and current_pool:
                    current_pool["numeric_id"] = line_str.split(":", 1)[1].strip()
                elif line_str.startswith("state:") and current_pool:
                    current_pool["status"] = line_str.split(":", 1)[1].strip()
            if current_pool.get("pool_id"):
                discovered.append(current_pool)
        return discovered

    def create_share(
        self,
        name: str,
        path: str,
        comment: str = "",
        security: str = "public",
        read_only: bool = False,
        export_smb: bool = True,
        export_nfs: bool = False,
        quota_gb: int = 0,
        user_permissions: dict[str, str] | None = None,
        nfs_squash: str = "no_root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "*",
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Network shares on Unraid must be provisioned via the Unraid WebGUI "
            "or /boot/config/shares to ensure proper Samba shfs driver integration."
        )

    def delete_share(self, name: str) -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Deleting network shares on Unraid must be performed via the Unraid WebGUI."
        )

    def rename_pool(self, pool_id: str, new_name: str) -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Storage pool and array identifiers on Unraid "
            "are authoritatively managed via Unraid Main / Array settings."
        )

    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
        worm_mode: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots on Unraid are authoritatively managed by Unraid."
        )

    def list_snapshots(self, pool_id: str) -> list[dict[str, Any]]:
        return []

    def delete_snapshot(
        self,
        pool_id: str,
        snapshot_name: str,
        break_glass: bool = False,
        reason: str = "",
    ) -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots on Unraid are authoritatively managed by Unraid."
        )

    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots and rollbacks on Unraid are authoritatively managed by Unraid."
        )

    def get_pool_path(self, pool_id: str) -> str:
        """Returns root mountpoint for an Unraid array or cache pool."""
        if pool_id and pool_id.startswith("cache_"):
            pool_key = pool_id.replace("cache_", "")
            for cand in [f"/mnt/{pool_key}", "/mnt/cache"]:
                if os.path.exists(cand):
                    return cand
        return pal_base.POOL_PATH or "/mnt/user"
