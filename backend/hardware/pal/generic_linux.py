"""Generic Linux: Btrfs, ZFS and mdadm pools, Samba and NFS shares managed here.

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
    _whole_disk,
)
from backend.hardware.share_compression import md_compression, pool_compression
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status
from backend.ignored_errors import ignored
from backend.settings import test_mode


class GenericLinuxStorageAdapter(StoragePlatformAdapter):
    """
    Generic Linux Storage Platform Adapter.
    Operates in Active Provisioner Mode (or Observer Mode when unprivileged).
    Supports Btrfs multi-device pools, ext4/xfs volumes, subvolume snapshots,
    and managed Samba/WebDAV shares.
    """

    def __init__(self, pool_path: str | None = None):
        self._pool_path = pool_path or pal_base.POOL_PATH or "/mnt/storage"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.GENERIC_LINUX

    def get_capabilities(self) -> PlatformCapabilities:
        from backend.hardware.pal.base import storage_tools

        tools = storage_tools()
        has_cow = tools["btrfs"] or tools["zfs"]
        missing = [n for n in ("btrfs", "zfs", "mdadm") if not tools[n]]
        return PlatformCapabilities(
            platform=PlatformType.GENERIC_LINUX,
            is_observer_mode=False,
            can_create_pools=True,
            can_destroy_pools=True,
            can_manage_shares=True,
            # REL-4: offer only what the tools in this image can do
            can_trigger_scrub=has_cow or tools["mdadm"],
            can_snapshot=has_cow,
            storage_tools=tools,
            supported_filesystems=[f for f in ("btrfs", "ext4", "xfs", "zfs") if f in ("ext4", "xfs") or tools[f]],
            description="Active Provisioner Mode: Bare-metal Linux host detected. Pool and share management enabled."
            + (f" Not available here: {', '.join(missing)} tools are missing." if missing else ""),
        )

    def _run_cmd(self, cmd: list[str]) -> tuple[int, str, str]:
        """Runs a system command with error capture."""
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except FileNotFoundError:
            return 127, "", f"Command not found: {cmd[0]}"
        except subprocess.TimeoutExpired:
            return 124, "", "Command timed out"
        except Exception as e:
            return 1, "", str(e)

    def _resolve_disk_path(self, disk: str) -> str:
        """
        Resolves relative or bare disk names to canonical block device path,
        strictly preferring persistent /dev/disk/by-id/ identifiers to prevent
        device node shuffling from corrupting external USB/TB and SATA pools.
        """
        d = disk.strip()
        # If already specified as a by-id or by-path canonical path
        if "/disk/by-" in d:
            if os.path.exists(d):
                return d
            host_p = os.path.join(pal_base.HOST_DEV, d.lstrip("/"))
            if os.path.exists(host_p):
                return host_p
            return d

        # Determine target dev name (e.g. "sda", "nvme1n1")
        base_name = os.path.basename(d)

        # Search for canonical persistent /dev/disk/by-id/ symlink
        for by_id_dir in ["/dev/disk/by-id", os.path.join(pal_base.HOST_DEV, "disk/by-id")]:
            if os.path.isdir(by_id_dir):
                try:
                    candidates = []
                    for entry in os.listdir(by_id_dir):
                        # Skip partition links
                        if re.search(r"-part\d+$", entry):
                            continue
                        link_path = os.path.join(by_id_dir, entry)
                        try:
                            target = os.path.realpath(link_path)
                            if os.path.basename(target) == base_name:
                                candidates.append(link_path)
                        except OSError:
                            continue

                    if candidates:
                        # Rank candidates: wwn- > ata- / nvme- > usb- > scsi-
                        def _rank(p: str) -> int:
                            name = os.path.basename(p)
                            if name.startswith("wwn-"):
                                return 0
                            if name.startswith("ata-") or name.startswith("nvme-"):
                                return 1
                            if name.startswith("usb-"):
                                return 2
                            if name.startswith("scsi-"):
                                return 3
                            return 4

                        candidates.sort(key=_rank)
                        return candidates[0]
                except Exception as e:
                    logger.debug(f"[PAL] by-id resolution error for {disk}: {e}")

        # Fallback to standard block device node
        if d.startswith("/"):
            if os.path.exists(d):
                return d
            host_disk = os.path.join(pal_base.HOST_DEV, d.lstrip("/"))
            if os.path.exists(host_disk):
                return host_disk
            return d

        for base in [pal_base.HOST_DEV, "/dev"]:
            cand = os.path.join(base, d)
            if os.path.exists(cand):
                return cand
        return f"/dev/{d}"

    _busy_cache_ts: float = 0.0
    _busy_cache_val: bool = False

    def is_storage_busy(self) -> bool:
        """Checks if a scrub or balance is actively running across Btrfs or OpenZFS pools (10s TTL cache)."""
        if test_mode():
            return self._check_is_storage_busy_uncached()
        now = time.time()
        if now - getattr(self, "_busy_cache_ts", 0.0) < 10.0:
            return getattr(self, "_busy_cache_val", False)

        val = self._check_is_storage_busy_uncached()
        self._busy_cache_ts = now
        self._busy_cache_val = val
        return val

    def _check_is_storage_busy_uncached(self) -> bool:
        # Check Btrfs scrub (e.g. "scrub status for ...: running" vs "no scrub running")
        code, out, _ = self._run_cmd(["btrfs", "scrub", "status", self._pool_path])
        out_l = out.lower()
        if code == 0 and ("running" in out_l and "no scrub" not in out_l and "not running" not in out_l):
            return True
        # Check Btrfs balance (e.g. "Balance on ... is running" vs "No balance found on ...")
        code, out, _ = self._run_cmd(["btrfs", "balance", "status", self._pool_path])
        out_l = out.lower()
        if code == 0 and ("is running" in out_l or "balance running" in out_l):
            return True
        # Check OpenZFS scrub/resilver
        code, out, _ = self._run_cmd(["zpool", "status"])
        out_l = out.lower()
        return bool(code == 0 and ("scrub in progress" in out_l or "resilver in progress" in out_l))

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        """Triggers or checks status of Btrfs scrub (or ZFS if pool_id is prefixed with 'zfs:')."""
        self._busy_cache_ts = 0.0
        if pool_id and (pool_id.startswith("zfs:") or pool_id.startswith("zpool:")):
            zp = pool_id.split(":", 1)[1]
            if action == "start":
                code, out, err = self._run_cmd(["zpool", "scrub", zp])
                return {
                    "platform": "zfs",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "started" if code == 0 else "error",
                    "output": out or err,
                }
            elif action == "cancel":
                code, out, err = self._run_cmd(["zpool", "scrub", "-s", zp])
                return {
                    "platform": "zfs",
                    "pool_id": pool_id,
                    "action": action,
                    "status": "cancelled" if code == 0 else "error",
                    "output": out or err,
                }
            else:
                code, out, err = self._run_cmd(["zpool", "status", zp])
                return {
                    "platform": "zfs",
                    "pool_id": pool_id,
                    "action": "status",
                    "status": "active" if "scrub in progress" in out.lower() else "idle",
                    "raw": out or err,
                }

        target_path = self._pool_path
        if action == "start":
            code, out, err = self._run_cmd(["btrfs", "scrub", "start", target_path])
            return {
                "platform": "generic_linux",
                "pool_id": pool_id,
                "action": action,
                "status": "started" if code == 0 else "error",
                "output": out or err,
                "message": f"Scrub initiated on {target_path}",
            }
        elif action == "cancel":
            code, out, err = self._run_cmd(["btrfs", "scrub", "cancel", target_path])
            return {
                "platform": "generic_linux",
                "pool_id": pool_id,
                "action": action,
                "status": "cancelled" if code == 0 else "error",
                "output": out or err,
            }
        else:
            code, out, err = self._run_cmd(["btrfs", "scrub", "status", "-d", target_path])
            return {
                "platform": "generic_linux",
                "pool_id": pool_id,
                "action": "status",
                "status": "idle" if ("no scrub running" in out.lower() or "not running" in out.lower()) else "active",
                "raw": out or err,
            }

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        is_overlay = self._is_os_overlay_or_emmc(self._pool_path)
        hal_disks = {d.name: d for d in self._discover_hal_disks()}
        mounts = self._parse_mounts()
        claimed_mount_paths: set = set()

        # 1. Discover mdadm Linux Software RAID arrays if present
        mdstats = self._parse_mdstat()
        data_md_arrays = [m for m, i in mdstats.items() if i.get("size_bytes", 0) >= 20 * 1024 * 1024 * 1024]
        has_multiple_md = len(data_md_arrays) > 1

        for md_dev, info in sorted(mdstats.items()):
            size_b = info.get("size_bytes", 0)
            if size_b < 20 * 1024 * 1024 * 1024:
                continue

            level = info.get("level", "raid5").lower()
            degraded = info.get("degraded", False)
            status = "DEGRADED" if degraded else "HEALTHY"
            parity = level in ("raid1", "raid5", "raid6", "raid10")

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
                        ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_pools")

            for m in mounts:
                dev = m.get("device", "")
                mp = m.get("mountpoint", "")
                if any(target in dev for target in md_devices):
                    mount_path = mp
                    claimed_mount_paths.add(mp)
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

        # 2. Discover bcache and block device mounts
        for m in mounts:
            dev = m.get("device", "")
            mp = m.get("mountpoint", "")
            fstype = m.get("fstype", "")
            if dev.startswith("/dev/bcache") or (
                dev.startswith(("/dev/sd", "/dev/nvme", "/dev/mapper")) and not dev.startswith("/dev/mmcblk")
            ):
                if self._is_os_overlay_or_emmc(mp) or mp in claimed_mount_paths:
                    continue
                if any(p.id == os.path.basename(dev) or p.mountpoint == mp for p in pools):
                    continue

                try:
                    u = shutil.disk_usage(mp)
                    tot, usd, fre = u.total, u.used, u.free
                except Exception:
                    continue

                if tot < 20 * 1024 * 1024 * 1024:
                    continue

                pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

                pool_members = []
                for d_name, d_rec in hal_disks.items():
                    if d_rec.role == "cache" or "nvme" in d_name:
                        pool_members.append(d_rec)
                if not pool_members:
                    pool_members = list(hal_disks.values())

                dev_base = os.path.basename(dev)
                p_name = (
                    "Fast Storage & Apps Pool (Btrfs)"
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
            for line in zout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 5:
                    zp_name = parts[0].strip()
                    zp_size, zp_alloc, zp_free, zp_health = (
                        parts[1].strip(),
                        parts[2].strip(),
                        parts[3].strip(),
                        parts[4].strip(),
                    )
                    try:
                        z_total = int(zp_size) if zp_size.isdigit() else 0
                        z_used = int(zp_alloc) if zp_alloc.isdigit() else 0
                        z_free = int(zp_free) if zp_free.isdigit() else 0
                        z_pct = round(z_used / z_total * 100, 1) if z_total > 0 else 0.0
                    except Exception:
                        z_total, z_used, z_free, z_pct = 0, 0, 0, 0.0

                    _, zmnt, _ = self._run_cmd(["zfs", "get", "-Hp", "-o", "value", "mountpoint", zp_name])
                    z_mount = zmnt.strip() if zmnt.strip() and zmnt.strip() != "none" else f"/{zp_name}"

                    _, zstat, _ = self._run_cmd(["zpool", "status", zp_name])
                    z_profile = "single"
                    zstat_l = zstat.lower()
                    if "raidz3" in zstat_l:
                        z_profile = "raidz3"
                    elif "raidz2" in zstat_l:
                        z_profile = "raidz2"
                    elif "raidz1" in zstat_l:
                        z_profile = "raidz1"
                    elif "mirror" in zstat_l:
                        z_profile = "mirror"

                    z_members = self._parse_zpool_members(zp_name)

                    pools.append(
                        StoragePool(
                            id=zp_name,
                            name=zp_name,
                            pool_type="zfs_raid"
                            if z_profile in ("raidz1", "raidz2", "raidz3")
                            else ("zfs_mirror" if z_profile == "mirror" else "zfs_single"),
                            fs_type="zfs",
                            fs_profile=z_profile,
                            status="HEALTHY" if zp_health == "ONLINE" else zp_health,
                            mountpoint=z_mount,
                            total_bytes=z_total,
                            used_bytes=z_used,
                            free_bytes=z_free,
                            used_pct=z_pct,
                            members=z_members,
                            parity_protected=z_profile in ("raidz1", "raidz2", "raidz3", "mirror"),
                            autotrim=True,
                            compression=pool_compression("zfs", z_mount, zp_name),
                        )
                    )

        # 4. Standard pool at self._pool_path
        if not is_overlay:
            total, used, free = 0, 0, 0
            try:
                u = shutil.disk_usage(self._pool_path if os.path.exists(self._pool_path) else "/")
                total, used, free = u.total, u.used, u.free
            except Exception:
                ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_pools")
            pct = round(used / total * 100, 1) if total > 0 else 0.0

            members = list(hal_disks.values()) if hal_disks else self._discover_hal_disks()

            profile = "raid1" if len(members) >= 2 else "single"
            code_df, out_df, _ = self._run_cmd(["btrfs", "filesystem", "df", self._pool_path])
            if code_df == 0 and out_df.strip():
                for line in out_df.strip().splitlines():
                    if line.startswith("Data,"):
                        match = re.search(r"Data,\s*([A-Za-z0-9_]+):", line)
                        if match:
                            profile = match.group(1).lower()
                            break
            else:
                code, out, _ = self._run_cmd(["btrfs", "filesystem", "show", self._pool_path])
                if code == 0:
                    if "raid10" in out.lower():
                        profile = "raid10"
                    elif "raid1" in out.lower():
                        profile = "raid1"
                    elif "raid0" in out.lower():
                        profile = "raid0"
                    elif "single" in out.lower():
                        profile = "single"

            parity_protected = profile in ("raid1", "raid10", "raid5", "raid6")

            if not any(p.mountpoint == self._pool_path for p in pools):
                pools.insert(
                    0,
                    StoragePool(
                        id="default_pool",
                        name="Primary Storage Pool",
                        pool_type="btrfs_raid" if len(members) >= 2 else "single",
                        fs_type="btrfs",
                        fs_profile=profile,
                        status="HEALTHY",
                        mountpoint=self._pool_path,
                        total_bytes=total,
                        used_bytes=used,
                        free_bytes=free,
                        used_pct=pct,
                        members=members,
                        parity_protected=parity_protected,
                        autotrim=True,
                        compression=pool_compression("btrfs", self._pool_path),
                    ),
                )
        elif not pools:
            try:
                u = shutil.disk_usage(self._pool_path if os.path.exists(self._pool_path) else "/")
                total, used, free = u.total, u.used, u.free
            except Exception:
                total, used, free = 0, 0, 0
            pct = round(used / total * 100, 1) if total > 0 else 0.0
            pools.append(
                StoragePool(
                    id="system_flash",
                    name="System Boot Flash (eMMC)",
                    pool_type="os_boot",
                    fs_type="overlay",
                    status="HEALTHY",
                    mountpoint=self._pool_path,
                    total_bytes=total,
                    used_bytes=used,
                    free_bytes=free,
                    used_pct=pct,
                    members=[],
                    parity_protected=False,
                )
            )

        return pools

    def list_shares(self) -> list[NetworkShare]:
        shares_map: dict[str, NetworkShare] = {}
        # 1. Inspect Samba Engine shares
        try:
            from backend.services.samba_engine import get_samba_engine

            engine = get_samba_engine()
            samba_shares = engine.list_shares()
            for s in samba_shares:
                mount_p = s.path
                try:
                    u = shutil.disk_usage(mount_p if os.path.exists(mount_p) else self._pool_path)
                    tot, usd, fre = u.total, u.used, u.free
                except Exception:
                    tot, usd, fre = 0, 0, 0
                pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

                shares_map[s.name] = NetworkShare(
                    name=s.name,
                    comment=s.comment or "ZettNAS Managed Share",
                    security="public" if s.guest_ok else "private",
                    export_smb=True,
                    export_nfs=False,
                    export_webdav=True,
                    cache_mode="none",
                    mountpoint=mount_p,
                    used_bytes=usd,
                    free_bytes=fre,
                    total_bytes=tot,
                    used_pct=pct,
                )
        except Exception as e:
            logger.debug(f"[PAL] SambaEngine shares query fallback: {e}")

        # 2. Inspect NFS Engine exports
        try:
            from backend.services.nfs_engine import get_nfs_engine

            nfs_engine = get_nfs_engine()
            for n in nfs_engine.list_exports():
                if n.name in shares_map:
                    shares_map[n.name].export_nfs = True
                else:
                    mount_p = n.path
                    try:
                        u = shutil.disk_usage(mount_p if os.path.exists(mount_p) else self._pool_path)
                        tot, usd, fre = u.total, u.used, u.free
                    except Exception:
                        tot, usd, fre = 0, 0, 0
                    pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

                    shares_map[n.name] = NetworkShare(
                        name=n.name,
                        comment=n.comment or "ZettNAS Managed NFS Export",
                        security="public" if n.clients == "*" else "private",
                        export_smb=False,
                        export_nfs=True,
                        export_webdav=False,
                        cache_mode="none",
                        mountpoint=mount_p,
                        used_bytes=usd,
                        free_bytes=fre,
                        total_bytes=tot,
                        used_pct=pct,
                    )
        except Exception as e:
            logger.debug(f"[PAL] NfsEngine exports query fallback: {e}")

        if shares_map:
            return list(shares_map.values())

        # 3. Filesystem directory fallback
        if os.path.isdir(self._pool_path):
            try:
                for entry in sorted(os.listdir(self._pool_path)):
                    sub_p = os.path.join(self._pool_path, entry)
                    if os.path.isdir(sub_p) and not entry.startswith((".", "@")):
                        try:
                            u = shutil.disk_usage(sub_p)
                            tot, usd, fre = u.total, u.used, u.free
                        except Exception:
                            tot, usd, fre = 0, 0, 0
                        pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                        shares_map[entry] = NetworkShare(
                            name=entry,
                            comment="Managed Linux Share",
                            security="public",
                            export_smb=True,
                            export_nfs=False,
                            export_webdav=True,
                            cache_mode="none",
                            mountpoint=sub_p,
                            used_bytes=usd,
                            free_bytes=fre,
                            total_bytes=tot,
                            used_pct=pct,
                        )
            except Exception as e:
                logger.debug(f"[PAL] Error listing generic shares: {e}")
        return list(shares_map.values())

    def _must(self, cmd: list[str], what: str) -> str:
        """Runs a step of pool creation; a failure stops it with the tool's own message."""
        code, out, err = self._run_cmd(cmd)
        if code != 0:
            raise RuntimeError(f"{what} failed ({code}): {(err or out or 'no output')[:300]}")
        return out

    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: list[str],
        mountpoint: str,
    ) -> dict[str, Any]:
        """Creates a multi-device Btrfs, OpenZFS, ext4, or XFS storage pool."""
        if not disks:
            raise ValueError("At least one disk must be specified to create a storage pool")

        resolved_disks = [self._resolve_disk_path(d) for d in disks]
        profile_lower = profile.lower()
        fs_lower = fs_type.lower()

        # Validate drive counts for RAID profiles
        if fs_lower == "zfs":
            if profile_lower == "raidz1" and len(resolved_disks) < 3:
                raise ValueError("OpenZFS RAIDZ1 requires at least 3 disks (single parity)")
            elif profile_lower == "raidz2" and len(resolved_disks) < 4:
                raise ValueError("OpenZFS RAIDZ2 requires at least 4 disks (dual parity)")
            elif profile_lower == "raidz3" and len(resolved_disks) < 5:
                raise ValueError("OpenZFS RAIDZ3 requires at least 5 disks (triple parity)")
            elif profile_lower in ("mirror", "raid1") and len(resolved_disks) < 2:
                raise ValueError("OpenZFS Mirror requires at least 2 disks")
        else:
            if profile_lower in ("raid1", "raid0") and len(resolved_disks) < 2:
                raise ValueError(f"{profile.upper()} requires at least 2 disks")
            if profile_lower == "raid10" and len(resolved_disks) < 4:
                raise ValueError("RAID10 requires at least 4 disks")

        target_mount = mountpoint.strip() or os.path.join(self._pool_path, name)
        try:
            os.makedirs(target_mount, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create target mount dir {target_mount}: {e}")

        if fs_lower == "zfs":
            # ashift=12 (4Kn/512e modern sector alignment), zstd compression, posixacl, xattr=sa
            vdev_type = profile_lower if profile_lower in ("raidz1", "raidz2", "raidz3", "mirror") else ""
            vdev_args = [vdev_type] + resolved_disks if vdev_type else resolved_disks
            cmd = [
                "zpool",
                "create",
                "-f",
                "-o",
                "ashift=12",
                "-O",
                "compression=zstd",
                "-O",
                "acltype=posixacl",
                "-O",
                "xattr=sa",
                "-O",
                "atime=off",
                "-m",
                target_mount,
                name,
            ] + vdev_args
            self._must(cmd, "zpool create")

        elif fs_lower == "btrfs":
            cmd = ["mkfs.btrfs", "-f", "-L", name, "-m", profile_lower, "-d", profile_lower] + resolved_disks
            self._must(cmd, "mkfs.btrfs")

            # Mount with modern zstd compression and fast noatime
            mount_cmd = ["mount", "-o", "compress=zstd:1,noatime,space_cache=v2", resolved_disks[0], target_mount]
            self._must(mount_cmd, "mount")

            # Create default subvolumes for shares and snapshots
            self._run_cmd(["btrfs", "subvolume", "create", os.path.join(target_mount, "@shares")])
            self._run_cmd(["btrfs", "subvolume", "create", os.path.join(target_mount, "@snapshots")])

        elif fs_lower == "ext4":
            self._must(["mkfs.ext4", "-F", "-L", name, resolved_disks[0]], "mkfs.ext4")
            self._must(["mount", resolved_disks[0], target_mount], "mount")

        elif fs_lower == "xfs":
            self._must(["mkfs.xfs", "-f", "-L", name, resolved_disks[0]], "mkfs.xfs")
            self._must(["mount", resolved_disks[0], target_mount], "mount")

        return {
            "status": "provisioned",
            "name": name,
            "fs_type": fs_lower,
            "profile": profile_lower,
            "mountpoint": target_mount,
            "disks": resolved_disks,
            "created_at": time.time(),
        }

    def rename_pool(self, pool_id: str, new_name: str) -> dict[str, Any]:
        """Renames a storage pool (ZFS export/import, Btrfs label) and creates compatibility symlink."""
        if not new_name or not new_name.strip():
            raise ValueError("New pool name cannot be empty")
        clean_name = new_name.strip()
        if pool_id == clean_name:
            return {
                "status": "unchanged",
                "pool_id": pool_id,
                "name": clean_name,
                "message": "Pool name unchanged",
            }

        # 1. Check if it's an OpenZFS pool
        code, _, _ = self._run_cmd(["zpool", "status", pool_id])
        if code == 0:
            exp_code, _, exp_err = self._run_cmd(["zpool", "export", pool_id])
            if exp_code != 0 and exp_code != 127:
                raise RuntimeError(f"Failed to export zpool '{pool_id}': {exp_err or 'active I/O or busy'}")

            imp_code, _, imp_err = self._run_cmd(["zpool", "import", pool_id, clean_name])
            if imp_code != 0 and imp_code != 127:
                self._run_cmd(["zpool", "import", pool_id])
                raise RuntimeError(f"Failed to import zpool as '{clean_name}': {imp_err}")

            old_mnt = os.path.join(self._pool_path, pool_id) if self._pool_path != "/mnt" else f"/mnt/{pool_id}"
            new_mnt = os.path.join(self._pool_path, clean_name) if self._pool_path != "/mnt" else f"/mnt/{clean_name}"
            try:
                if os.path.exists(old_mnt) and not os.path.islink(old_mnt):
                    try:
                        os.rmdir(old_mnt)
                    except Exception:
                        ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.rename_pool")
                if not os.path.exists(old_mnt):
                    os.symlink(new_mnt, old_mnt)
                    logger.info(f"[PAL] Created compatibility symlink {old_mnt} -> {new_mnt}")
            except Exception as e:
                logger.warning(f"[PAL] Could not create compatibility symlink {old_mnt} -> {new_mnt}: {e}")

            return {
                "status": "renamed",
                "old_name": pool_id,
                "new_name": clean_name,
                "fs_type": "zfs",
                "mountpoint": new_mnt,
                "compat_symlink": old_mnt,
            }

        # 2. Check if Btrfs or generic pool directory
        old_mnt = os.path.join(self._pool_path, pool_id) if pool_id != "default_pool" else self._pool_path
        new_mnt = os.path.join(os.path.dirname(old_mnt), clean_name) if pool_id != "default_pool" else old_mnt

        btrfs_code, _, _ = self._run_cmd(["btrfs", "filesystem", "label", old_mnt, clean_name])

        if pool_id != "default_pool" and old_mnt != new_mnt:
            try:
                if os.path.exists(old_mnt) and not os.path.exists(new_mnt):
                    os.rename(old_mnt, new_mnt)
                    os.symlink(new_mnt, old_mnt)
                    logger.info(f"[PAL] Renamed directory {old_mnt} -> {new_mnt} and created compatibility symlink")
            except Exception as e:
                logger.warning(f"[PAL] Directory rename or symlink creation error: {e}")

        return {
            "status": "renamed",
            "old_name": pool_id,
            "new_name": clean_name,
            "fs_type": "btrfs" if btrfs_code == 0 else "generic",
            "mountpoint": new_mnt,
            "compat_symlink": old_mnt if old_mnt != new_mnt else None,
        }

    def destroy_pool(self, pool_id: str) -> dict[str, Any]:
        """Safely unmounts and removes a storage pool."""
        target_mount = os.path.join(self._pool_path, pool_id) if pool_id != "default_pool" else self._pool_path
        code, out, err = self._run_cmd(["umount", "-f", target_mount])
        return {
            "status": "destroyed",
            "pool_id": pool_id,
            "mountpoint": target_mount,
            "unmount_code": code,
        }

    def export_pool(self, pool_id: str, force: bool = False) -> dict[str, Any]:
        """Safely flushes dirty write cache, checks active file handles, and exports or unmounts a storage pool."""
        code, _, _ = self._run_cmd(["zpool", "status", pool_id])
        is_zfs = code == 0

        target_mount = os.path.join(self._pool_path, pool_id) if pool_id != "default_pool" else self._pool_path
        if is_zfs:
            c_mnt, o_mnt, _ = self._run_cmd(["zfs", "get", "-H", "-o", "value", "mountpoint", pool_id])
            if c_mnt == 0 and o_mnt.strip() and o_mnt.strip() != "none":
                target_mount = o_mnt.strip()

        # Check for active file handles holding the mountpoint
        active_handles = []
        if os.path.exists(target_mount):
            c_fu, o_fu, _ = self._run_cmd(["fuser", "-m", target_mount])
            if c_fu == 0 and o_fu.strip():
                pids = o_fu.strip().split()
                active_handles.extend([f"PID {p}" for p in pids[:10]])

        if active_handles and not force:
            raise RuntimeError(
                f"Storage pool '{pool_id}' has {len(active_handles)} active process(es) holding open handles: "
                f"{', '.join(active_handles)}. Specify force=true to unmount and export anyway."
            )

        # Flush filesystem write caches
        self._run_cmd(["sync"])

        if is_zfs:
            exp_cmd = ["zpool", "export", "-f", pool_id] if force else ["zpool", "export", pool_id]
            c_exp, _, err_exp = self._run_cmd(exp_cmd)
            if c_exp != 0:
                raise RuntimeError(f"Failed to export zpool '{pool_id}': {err_exp or 'busy or in use'}")
            fs_type = "zfs"
        else:
            um_cmd = ["umount", "-f", target_mount] if force else ["umount", target_mount]
            c_um, _, err_um = self._run_cmd(um_cmd)
            if c_um != 0:
                raise RuntimeError(f"Failed to unmount pool '{pool_id}': {err_um or 'busy or in use'}")
            fs_type = "generic"

        return {
            "status": "exported",
            "pool_id": pool_id,
            "fs_type": fs_type,
            "mountpoint": target_mount,
            "safe_to_disconnect": True,
            "message": f"Storage pool '{pool_id}' safely exported and flushed. Safe to disconnect cable.",
        }

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: str | None = None) -> dict[str, Any]:
        """Imports an external storage pool from an attached enclosure."""
        fs_lower = fs_type.lower()
        if fs_lower == "zfs":
            code, out, err = self._run_cmd(["zpool", "import", "-f", pool_id])
            if code != 0:
                raise RuntimeError(f"Failed to import zpool '{pool_id}': {err or out}")
            return {
                "status": "imported",
                "pool_id": pool_id,
                "fs_type": "zfs",
                "message": f"OpenZFS pool '{pool_id}' successfully imported.",
            }
        else:
            self._run_cmd(["btrfs", "device", "scan"])
            mnt = target_mount or os.path.join(self._pool_path, pool_id)
            os.makedirs(mnt, exist_ok=True)
            code, out, err = self._run_cmd(["mount", "-L", pool_id, mnt])
            if code != 0:
                code, out, err = self._run_cmd(["mount", f"/dev/disk/by-label/{pool_id}", mnt])
            return {
                "status": "imported" if code == 0 else "error",
                "pool_id": pool_id,
                "fs_type": fs_lower,
                "mountpoint": mnt,
                "message": f"Pool '{pool_id}' imported at {mnt}" if code == 0 else f"Failed to mount: {err}",
            }

    def discover_external_pools(self) -> list[dict[str, Any]]:
        """Scans for unmounted external storage pools available to import."""
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
        nfs_squash: str = "root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "",
    ) -> dict[str, Any]:
        """Provisions a network share and syncs with SambaEngine and NfsEngine."""
        from backend.services.samba_engine import validate_share_path

        full_path = validate_share_path(path if path else os.path.join(self._pool_path, name))
        if export_nfs:  # refuse bad NFS settings before anything is created
            from backend.services.nfs_engine import NfsExportRule, home_network

            try:
                NfsExportRule(
                    name=name,
                    path=full_path,
                    clients=nfs_clients.strip() or home_network(),
                    squash=nfs_squash or "root_squash",
                    comment=comment,
                )
            except Exception as e:
                raise ValueError(f"Invalid NFS export settings: {e}") from e
        try:
            os.makedirs(full_path, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create share dir {full_path}: {e}")

        user_perms = user_permissions or {}
        valid_users = None
        read_list = None
        write_list = None

        if user_perms:
            rw_users = [u for u, p in user_perms.items() if p == "rw"]
            ro_users = [u for u, p in user_perms.items() if p == "ro"]
            all_allowed = rw_users + ro_users
            if all_allowed:
                valid_users = " ".join(all_allowed)
            if ro_users:
                read_list = " ".join(ro_users)
            if rw_users:
                write_list = " ".join(rw_users)

        if export_smb:
            try:
                from backend.services.samba_engine import SambaShareConfig, get_samba_engine

                engine = get_samba_engine()
                share_cfg = SambaShareConfig(
                    name=name,
                    path=full_path,
                    comment=comment,
                    read_only=read_only,
                    guest_ok=(security == "public"),
                    browseable=True,
                    quota_gb=quota_gb if quota_gb > 0 else None,
                    valid_users=valid_users,
                    read_list=read_list,
                    write_list=write_list,
                )
                engine.add_or_update_share(share_cfg)
            except ValueError:
                raise  # refused settings (SEC-06): stop here, before anything is exported over NFS
            except Exception as e:
                logger.warning(f"[PAL] SambaEngine registration failed: {e}")

        if export_nfs:
            from backend.services.nfs_engine import NfsExportRule, home_network

            try:
                rule = NfsExportRule(
                    name=name,
                    path=full_path,
                    clients=nfs_clients.strip() or home_network(),
                    permission="ro" if read_only else "rw",
                    squash=nfs_squash or "root_squash",
                    anonuid=nfs_anonuid,
                    anongid=nfs_anongid,
                    sync_mode="sync" if nfs_sync else "async",
                    comment=comment,
                )
            except Exception as e:  # pydantic ValidationError: a refused setting
                raise ValueError(f"Invalid NFS export settings: {e}") from e
            try:
                from backend.services.nfs_engine import get_nfs_engine

                get_nfs_engine().add_or_update_export(rule)
            except Exception as e:
                logger.warning(f"[PAL] NfsEngine registration failed: {e}")

        return {
            "status": "created",
            "name": name,
            "mountpoint": full_path,
            "comment": comment,
            "security": security,
            "read_only": read_only,
            "export_smb": export_smb,
            "export_nfs": export_nfs,
            "quota_gb": quota_gb,
            "user_permissions": user_perms,
        }

    def delete_share(self, name: str) -> dict[str, Any]:
        """Deletes a network share from Samba and NFS configurations."""
        try:
            from backend.services.samba_engine import get_samba_engine

            engine = get_samba_engine()
            engine.remove_share(name)
        except Exception as e:
            logger.warning(f"[PAL] Failed deleting share from SambaEngine: {e}")

        try:
            from backend.services.nfs_engine import get_nfs_engine

            nfs_engine = get_nfs_engine()
            nfs_engine.remove_export(name)
        except Exception as e:
            logger.warning(f"[PAL] Failed deleting share from NfsEngine: {e}")

        return {"status": "deleted", "name": name}

    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
        worm_mode: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        """Creates an atomic Btrfs subvolume snapshot with optional Two-Tier WORM immutability."""
        src_path = os.path.join(self._pool_path, "@shares", subvol_name)
        if not os.path.exists(src_path):
            src_path = os.path.join(self._pool_path, subvol_name)

        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        try:
            os.makedirs(snaps_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create snapshots dir {snaps_dir}: {e}")
        dest_path = os.path.join(snaps_dir, snapshot_name)

        # Force readonly for WORM snapshots
        if worm_mode in ("compliance", "governance"):
            readonly = True

        cmd = ["btrfs", "subvolume", "snapshot"]
        if readonly:
            cmd.append("-r")
        cmd.extend([src_path, dest_path])
        code, out, err = self._run_cmd(cmd)

        now = time.time()
        retention_until = None
        if worm_mode in ("compliance", "governance"):
            days = retention_days if (retention_days and retention_days > 0) else 30
            retention_until = now + (days * 86400)
            worm_meta = {
                "snapshot_name": snapshot_name,
                "pool_id": pool_id,
                "subvol_name": subvol_name,
                "worm_mode": worm_mode.lower(),
                "created_at": now,
                "retention_until": retention_until,
            }
            meta_path = os.path.join(snaps_dir, f".{snapshot_name}.worm.json")
            try:
                atomic_write_json(meta_path, worm_meta, indent=2)
            except Exception as e:
                logger.warning(f"[PAL] Failed saving WORM metadata: {e}")

        return {
            "status": "created" if code == 0 else "error",  # 127 = btrfs missing: not created (REL-4)
            "source": src_path,
            "snapshot": dest_path,
            "readonly": readonly,
            "worm_mode": worm_mode,
            "retention_until": retention_until,
            "code": code,
            "output": out or err,
        }

    def list_snapshots(self, pool_id: str) -> list[dict[str, Any]]:
        """Lists active Btrfs subvolume snapshots with WORM immutability metadata."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        snapshots: list[dict[str, Any]] = []
        if os.path.isdir(snaps_dir):
            try:
                for entry in sorted(os.listdir(snaps_dir)):
                    if entry.startswith("."):
                        continue
                    p = os.path.join(snaps_dir, entry)
                    if os.path.isdir(p):
                        stat = os.stat(p)
                        item = {
                            "name": entry,
                            "path": p,
                            "created_at": stat.st_mtime,
                            "pool_id": pool_id,
                            "worm_mode": None,
                            "retention_until": None,
                            "is_immutable": False,
                        }
                        meta_path = os.path.join(snaps_dir, f".{entry}.worm.json")
                        if os.path.isfile(meta_path):
                            try:
                                with open(meta_path, encoding="utf-8") as f:
                                    meta = json.load(f)
                                item["worm_mode"] = meta.get("worm_mode")
                                item["retention_until"] = meta.get("retention_until")
                                item["is_immutable"] = (meta.get("retention_until") or 0) > time.time()
                            except Exception:
                                ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_snapshots")
                        snapshots.append(item)
            except Exception as e:
                logger.debug(f"[PAL] Snapshot list error: {e}")
        return snapshots

    def delete_snapshot(
        self,
        pool_id: str,
        snapshot_name: str,
        break_glass: bool = False,
        reason: str = "",
    ) -> dict[str, Any]:
        """Deletes a Btrfs subvolume snapshot, strictly enforcing Two-Tier WORM immutability."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        target_path = os.path.join(snaps_dir, snapshot_name)
        meta_path = os.path.join(snaps_dir, f".{snapshot_name}.worm.json")

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                mode = (meta.get("worm_mode") or "").lower()
                retention_until = meta.get("retention_until") or 0
                now = time.time()
                if now < retention_until:
                    if mode == "compliance":
                        raise PlatformCapabilityError(
                            f"Compliance WORM lock active: Snapshot '{snapshot_name}' cannot be deleted until retention expires on {time.ctime(retention_until)}."
                        )
                    elif mode == "governance" and not break_glass:
                        raise PlatformCapabilityError(
                            f"Governance WORM lock active: Snapshot '{snapshot_name}' requires Break-Glass authorization and audit justification to delete."
                        )
            except PlatformCapabilityError:
                raise
            except Exception as e:
                logger.warning(f"[PAL] Error reading WORM metadata during delete: {e}")

        # If break_glass was invoked for governance snapshot, log security audit event
        if break_glass:
            try:
                from backend.users_db import log_security_event

                log_security_event(
                    event_type="worm_break_glass_delete",
                    status="success",
                    details={"snapshot": snapshot_name, "pool_id": pool_id, "reason": reason},
                )
            except Exception as e:
                logger.warning(f"[PAL] Security audit log error: {e}")

        code, out, err = self._run_cmd(["btrfs", "subvolume", "delete", target_path])
        if os.path.isfile(meta_path) and code in (0, 127):
            try:
                os.remove(meta_path)
            except OSError:
                pass

        return {
            "status": "deleted" if code in (0, 127) else "error",
            "snapshot": snapshot_name,
            "path": target_path,
            "code": code,
        }

    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> dict[str, Any]:
        """Restores or rolls back a Btrfs subvolume snapshot into active subvolume path."""
        snap_path = os.path.join(self._pool_path, "@snapshots", snapshot_name)
        if not os.path.exists(snap_path):
            return {"status": "error", "message": f"Snapshot {snapshot_name} not found at {snap_path}", "code": 1}

        subvol = target_subvol.strip()
        if not subvol:
            subvol = snapshot_name.split("_")[0] if "_" in snapshot_name else "restored_" + snapshot_name

        dest_dir = os.path.join(self._pool_path, "@shares")
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError:
            pass
        dest_path = os.path.join(dest_dir, subvol)

        archived_path = None
        if os.path.exists(dest_path):
            ts = int(time.time())
            archived_path = f"{dest_path}.pre_restore.{ts}"
            try:
                os.rename(dest_path, archived_path)
            except OSError as e:
                logger.warning(f"[PAL] Could not archive pre-existing subvolume {dest_path}: {e}")

        # Btrfs snapshot restore creates a writable subvolume clone from the read-only snapshot
        cmd = ["btrfs", "subvolume", "snapshot", snap_path, dest_path]
        code, out, err = self._run_cmd(cmd)

        return {
            "status": "restored" if code in (0, 127) else "error",
            "snapshot": snap_path,
            "target": dest_path,
            "archived_previous": archived_path,
            "code": code,
            "output": out or err,
        }

    def get_pool_path(self, pool_id: str) -> str:
        """Returns root mountpoint for a generic Linux storage pool."""
        if not pool_id or pool_id in ("default_pool", "default"):
            return self._pool_path
        cand = os.path.join(self._pool_path, pool_id)
        return cand if os.path.exists(cand) else self._pool_path
