"""ZettOS (Zettlab appliances): observed.

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
    PoolMember,
    StoragePool,
    _whole_disk,
)
from backend.hardware.pal.observer import ObserverStorageAdapter
from backend.hardware.share_compression import md_compression
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status
from backend.ignored_errors import ignored


class ZettOSStorageAdapter(ObserverStorageAdapter):
    """
    ZettOS Appliance Storage Platform Adapter.
    Operates in Observer Mode across all Zettlab models (D4, D6, D6U, D8U).
    ZettOS authoritatively manages multi-array mdadm RAID groups, bcache acceleration,
    OpenZFS pools, and network shares.
    """

    def get_platform_type(self) -> PlatformType:
        return PlatformType.ZETTOS

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.ZETTOS,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=True,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["zfs", "btrfs", "xfs"],
            description="Observer Mode: ZettOS appliance host detected. Hybrid ZFS/Btrfs storage pools, parity groups, and shares are authoritatively managed by ZettOS. Telemetry and scrub monitoring enabled.",
        )

    def is_storage_busy(self) -> bool:
        code, out, _ = self._run_cmd(["zpool", "status"])
        if code == 0 and ("scrub in progress" in out.lower() or "resilver in progress" in out.lower()):
            return True
        code, out, _ = self._run_cmd(["btrfs", "scrub", "status", self._pool_path])
        if code == 0 and (
            "running" in out.lower() and "no scrub" not in out.lower() and "not running" not in out.lower()
        ):
            return True
        mdstats = self._parse_mdstat()
        return any(md_info.get("sync_action") for md_info in mdstats.values())

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        zp = pool_id if (pool_id and pool_id != "default_pool") else "tank"
        if pool_id and ("zfs" in pool_id.lower() or "tank" in pool_id.lower()):
            if action == "start":
                code, out, err = self._run_cmd(["zpool", "scrub", zp])
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "started" if code == 0 else "error",
                    "output": out or err,
                }
            elif action == "cancel":
                code, out, err = self._run_cmd(["zpool", "scrub", "-s", zp])
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "cancelled" if code == 0 else "error",
                    "output": out or err,
                }
            else:
                code, out, err = self._run_cmd(["zpool", "status", zp])
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": "status",
                    "status": "active" if "scrub in progress" in out.lower() else "idle",
                    "raw": out or err,
                }
        elif pool_id and (pool_id.startswith("md") or pool_id.startswith("/dev/md")):
            clean_md = os.path.basename(pool_id)
            mdstats = self._parse_mdstat()
            md_info = mdstats.get(clean_md, {})
            sync_action = md_info.get("sync_action")
            progress_pct = md_info.get("progress_pct", 0.0)
            if action == "start":
                for base in [pal_base.HOST_SYS, "/sys", "/host/sys"]:
                    if not base:
                        continue
                    sa_path = os.path.join(base, "block", clean_md, "md/sync_action")
                    if os.path.exists(sa_path):
                        try:
                            with open(sa_path, "w") as f:
                                f.write("check\n")
                            return {
                                "platform": "zettos",
                                "pool_id": pool_id,
                                "action": action,
                                "status": "started",
                                "sync_action": "check",
                            }
                        except Exception:
                            ignored("backend.hardware.pal_storage.ZettOSStorageAdapter.trigger_scrub")
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "active" if sync_action else "monitoring",
                    "sync_action": sync_action or "idle",
                    "progress_pct": progress_pct,
                    "message": "ZettOS manages RAID parity sync via kernel mdadm.",
                }
            elif action == "cancel":
                # Only a scrub (check/repair) is stopped: "idle" during a resync or recovery would
                # interrupt the rebuild of a replaced disk and leave the array degraded longer.
                if sync_action and sync_action not in ("check", "repair"):
                    return {
                        "platform": "zettos",
                        "pool_id": pool_id,
                        "action": action,
                        "status": "active",
                        "sync_action": sync_action,
                        "progress_pct": progress_pct,
                        "message": f"The array is running a {sync_action}, not a scrub; it was left running.",
                    }
                for base in [pal_base.HOST_SYS, "/sys", "/host/sys"]:
                    if not base:
                        continue
                    sa_path = os.path.join(base, "block", clean_md, "md/sync_action")
                    if os.path.exists(sa_path):
                        try:
                            with open(sa_path, "w") as f:
                                f.write("idle\n")
                            return {
                                "platform": "zettos",
                                "pool_id": pool_id,
                                "action": action,
                                "status": "cancelled",
                                "sync_action": "idle",
                            }
                        except Exception:
                            ignored("backend.hardware.pal_storage.ZettOSStorageAdapter.trigger_scrub")
                return {"platform": "zettos", "pool_id": pool_id, "action": action, "status": "idle"}
            else:
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": "status",
                    "status": "active" if sync_action else "idle",
                    "sync_action": sync_action or "idle",
                    "progress_pct": progress_pct,
                }
        else:
            target_path = self._pool_path
            if action == "start":
                code, out, err = self._run_cmd(["btrfs", "scrub", "start", target_path])
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "started" if code == 0 else "error",
                    "output": out or err,
                }
            elif action == "cancel":
                code, out, err = self._run_cmd(["btrfs", "scrub", "cancel", target_path])
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "cancelled" if code == 0 else "error",
                    "output": out or err,
                }
            else:
                code, out, err = self._run_cmd(["btrfs", "scrub", "status", target_path])
                return {
                    "platform": "zettos",
                    "pool_id": pool_id,
                    "action": "status",
                    "status": "idle" if ("no scrub" in out.lower() or "not running" in out.lower()) else "active",
                    "raw": out or err,
                }

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        for cfg_cand in ["/etc/zettos/storage.json", "/host/etc/zettos/storage.json", "/etc/zettos/pools.json"]:
            if os.path.isfile(cfg_cand):
                try:
                    with open(cfg_cand, encoding="utf-8") as f:
                        cfg_data = json.load(f)
                        raw_list = cfg_data if isinstance(cfg_data, list) else cfg_data.get("pools", [])
                        for p_dict in raw_list:
                            pools.append(StoragePool(**p_dict))
                except Exception as e:
                    logger.debug(f"[PAL] Error reading ZettOS storage config: {e}")
        if pools:
            return pools

        claimed_mount_paths: set = set()

        # 1. Discover mdadm Linux Software RAID arrays (e.g. md3 RAID5/6 on Zettlab D4/D6/D8U)
        mdstats = self._parse_mdstat()
        hal_disks = {d.name: d for d in self._discover_hal_disks()}
        mounts = self._parse_mounts()

        # Count multi-array data pools to determine whether disambiguation is required
        data_md_arrays = [m for m, i in mdstats.items() if i.get("size_bytes", 0) >= 20 * 1024 * 1024 * 1024]
        has_multiple_md = len(data_md_arrays) > 1

        for md_dev, info in sorted(mdstats.items()):
            size_b = info.get("size_bytes", 0)
            # Skip small OS mirror / swap arrays (e.g. md0 94MB, md1 10GB)
            if size_b < 20 * 1024 * 1024 * 1024:
                continue

            level = info.get("level", "raid5").lower()
            degraded = info.get("degraded", False)
            status = "DEGRADED" if degraded else "HEALTHY"
            parity = level in ("raid1", "raid5", "raid6", "raid10")

            # Map members to physical HAL disks
            members: list[PoolMember] = []
            for m_token in info.get("members", []):
                clean_disk = _whole_disk(m_token)
                if clean_disk in hal_disks:
                    members.append(hal_disks[clean_disk])
                else:
                    members.append(
                        PoolMember(
                            name=m_token,
                            device=clean_disk,
                            id=m_token,
                            type="Data" if "nvme" not in clean_disk else "Cache",
                            role="data" if "nvme" not in clean_disk else "cache",
                            status="OK" if not degraded else "DEGRADED",
                        )
                    )

            # Check if this md array (or a filesystem on it) is mounted
            mount_path = None
            md_devices = {md_dev, f"/dev/{md_dev}"}
            for s_base in (pal_base.HOST_SYS, "/sys", "/host/sys"):
                if not s_base:
                    continue
                holders_dir = os.path.join(s_base, "block", md_dev, "holders")
                if os.path.isdir(holders_dir):
                    try:
                        for h in os.listdir(holders_dir):
                            md_devices.add(h)
                            md_devices.add(f"/dev/{h}")
                            md_devices.add(f"/dev/mapper/{h}")
                    except Exception:
                        ignored("backend.hardware.pal_storage.ZettOSStorageAdapter.list_pools")

            # Check container mounts for matching block device or subvolume
            for m in mounts:
                dev = m.get("device", "")
                mp = m.get("mountpoint", "")
                if any(target in dev for target in md_devices):
                    mount_path = mp
                    claimed_mount_paths.add(mp)
                    break

            # Check known ZettOS pool directories without collision
            if not mount_path:
                for cand_dir in [
                    f"/zettos/pool/{md_dev}",
                    "/zettos/pool/1",
                    "/zettos/pool/2",
                    "/zettos/pool/3",
                    "/zettos/pool/4",
                    "/zettos/pool/data",
                    "/zettos/pool/fast",
                    "/zettos/pool/apps",
                    "/mnt/storage",
                    "/mnt/user",
                ]:
                    if (
                        cand_dir not in claimed_mount_paths
                        and os.path.exists(cand_dir)
                        and not self._is_os_overlay_or_emmc(cand_dir)
                    ):
                        mount_path = cand_dir
                        claimed_mount_paths.add(cand_dir)
                        break

            size_b, used_b, free_b, pct, resolved_fstype = self._get_mount_or_device_usage(
                mount_path=mount_path,
                dev_name=md_dev,
                fallback_total=size_b,
            )

            is_nvme_array = "nvme" in str(members[0].device if members else "")
            if not has_multiple_md:
                friendly_name = (
                    f"Primary Storage Array ({level.upper()})"
                    if not is_nvme_array
                    else f"NVMe Storage Array ({level.upper()})"
                )
            else:
                friendly_name = (
                    f"Storage Array {md_dev.upper()} ({level.upper()})"
                    if not is_nvme_array
                    else f"NVMe Storage Array {md_dev.upper()} ({level.upper()})"
                )

            pools.append(
                StoragePool(
                    id=md_dev,
                    name=friendly_name,
                    pool_type=f"md_{level}",
                    fs_type=resolved_fstype or ("btrfs" if mount_path and "btrfs" in str(mounts) else "ext4"),
                    fs_profile=level,
                    status=status,
                    mountpoint=mount_path or f"/{md_dev}",
                    total_bytes=size_b,
                    used_bytes=used_b,
                    free_bytes=free_b,
                    used_pct=pct,
                    members=members,
                    parity_protected=parity,
                    autotrim="nvme" in str(members),
                    compression=md_compression(str(resolved_fstype or mounts), mount_path),
                )
            )

        # 2. Discover bcache and block device mounts (e.g. /app/data on /dev/bcache2, btrfs)
        for m in mounts:
            dev = m.get("device", "")
            mp = m.get("mountpoint", "")
            fstype = m.get("fstype", "")
            if dev.startswith("/dev/bcache") or (
                dev.startswith(("/dev/sd", "/dev/nvme", "/dev/mapper")) and not dev.startswith("/dev/mmcblk")
            ):
                if self._is_os_overlay_or_emmc(mp) or mp in claimed_mount_paths:
                    continue
                # Don't duplicate if already added
                if any(p.id == os.path.basename(dev) or p.mountpoint == mp for p in pools):
                    continue

                tot, usd, fre, pct, resolved_fs = self._get_mount_or_device_usage(
                    mount_path=mp,
                    dev_name=os.path.basename(dev),
                    fallback_total=0,
                )
                if tot < 20 * 1024 * 1024 * 1024:
                    continue

                claimed_mount_paths.add(mp)
                if resolved_fs:
                    fstype = resolved_fs

                pool_members = []
                for d_name, d_rec in hal_disks.items():
                    if d_rec.role == "cache" or "nvme" in d_name:
                        pool_members.append(d_rec)
                if not pool_members:
                    pool_members = list(hal_disks.values())

                dev_base = os.path.basename(dev)
                p_name = (
                    f"Fast Storage ({dev_base.upper()})"
                    if "bcache" in dev or "nvme" in dev
                    else f"{dev_base} ({fstype.upper()})"
                )
                pools.append(
                    StoragePool(
                        id=dev_base,
                        name=p_name,
                        pool_type="btrfs" if fstype == "btrfs" else "single",
                        fs_type=fstype,
                        fs_profile="single",
                        status="HEALTHY",
                        mountpoint=mp,
                        total_bytes=tot,
                        used_bytes=usd,
                        free_bytes=fre,
                        used_pct=pct,
                        members=pool_members,
                        parity_protected=True,
                    )
                )

        # 3. Discover OpenZFS pools
        code, zout, _ = self._run_cmd(["zpool", "list", "-Hp", "-o", "name,size,alloc,free,health"])
        if code == 0 and zout.strip():
            hal_disks_list = self._discover_hal_disks()
            for line in zout.strip().splitlines():
                parts = line.split("	")
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
                    z_members = self._parse_zpool_members(zp_name) or hal_disks_list
                    pools.append(
                        StoragePool(
                            id=zp_name,
                            name=f"{zp_name} (ZettOS ZFS Pool)",
                            pool_type="zfs_pool",
                            fs_type="zfs",
                            status="HEALTHY" if zp_health == "ONLINE" else zp_health,
                            mountpoint=f"/{zp_name}",
                            total_bytes=tot,
                            used_bytes=usd,
                            free_bytes=fre,
                            used_pct=pct,
                            members=z_members,
                            parity_protected=True,
                        )
                    )

        # 4. Fallback: only if no pools found at all
        if not pools:
            cand = self._pool_path if os.path.exists(self._pool_path) else "/"
            is_overlay = self._is_os_overlay_or_emmc(cand)
            try:
                u = shutil.disk_usage(cand)
                tot, usd, fre = u.total, u.used, u.free
            except Exception:
                tot, usd, fre = 0, 0, 0
            pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
            pools.append(
                StoragePool(
                    id="system_flash" if is_overlay else "zettos_pool",
                    name="System Boot Flash (eMMC)" if is_overlay else "ZettOS Main Storage Pool",
                    pool_type="os_boot" if is_overlay else "btrfs_raid",
                    fs_type="overlay" if is_overlay else "btrfs",
                    status="HEALTHY",
                    mountpoint=cand,
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=[] if is_overlay else self._discover_hal_disks(),
                    parity_protected=not is_overlay,
                )
            )

        return pools

    def list_shares(self) -> list[NetworkShare]:
        shares: list[NetworkShare] = []
        for s_cand in ["/etc/zettos/shares.json", "/host/etc/zettos/shares.json"]:
            if os.path.isfile(s_cand):
                try:
                    with open(s_cand, encoding="utf-8") as f:
                        data = json.load(f)
                        raw_list = data if isinstance(data, list) else data.get("shares", [])
                        for s in raw_list:
                            shares.append(NetworkShare(**s))
                except Exception as e:
                    logger.debug(f"[PAL] Error reading ZettOS shares config: {e}")
        if shares:
            return shares

        shares = self._parse_smb_conf()
        if not shares:
            shares = self._discover_shares_from_dirs(
                [
                    "/zettos/pool/1",
                    "/zettos/pool/2",
                    "/zettos/pool/3",
                    "/zettos/pool/data",
                    "/zettos/pool/storage",
                    "/zettos/pool",
                    "/zettos",
                    "/mnt/user",
                    "/mnt/storage",
                    self._pool_path,
                ]
            )
        return shares
