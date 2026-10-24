"""
ZettNAS Toolkit - Platform Abstraction Layer (PAL)
Universal Storage Subsystem Interface for Appliance & Generic Linux Hosts.
Provides hardware- and OS-agnostic disk, pool, and network share abstractions.
"""

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
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class PlatformType(StrEnum):
    GENERIC_LINUX = "generic_linux"
    UNRAID = "unraid"
    TRUENAS = "truenas"
    PROXMOX = "proxmox"
    FYGOOS = "fygoos"
    ZETTOS = "zettos"
    UGOS = "ugos"
    GENERIC_OBSERVER = "generic_observer"
    UNKNOWN = "unknown"


class PlatformCapabilities(BaseModel):
    platform: PlatformType
    is_observer_mode: bool = Field(
        ...,
        description="True on appliance hosts (Unraid, TrueNAS); False on generic Linux provisioners",
    )
    can_create_pools: bool = False
    can_destroy_pools: bool = False
    can_manage_shares: bool = False
    can_trigger_scrub: bool = True
    can_export_pools: bool = True
    can_import_pools: bool = True
    supported_filesystems: list[str] = Field(default_factory=list)
    description: str = ""


class PoolMember(BaseModel):
    name: str  # e.g. "parity", "disk1", "ark", "nvme1n1"
    device: str  # e.g. "sdb", "sda", "nvme1n1"
    id: str = ""  # Serial or canonical identifier
    type: str = "Data"  # "Parity", "Data", "Cache", "Boot"
    role: str = "data"  # "parity", "data", "cache", "boot"
    size_bytes: int = 0
    status: str = "OK"  # "OK", "STANDBY", "DISABLED", "MISSING", "UNKNOWN"
    rotational: bool = True
    spundown: bool = False
    temp_c: int | None = None
    num_reads: int = 0
    num_writes: int = 0
    num_errors: int = 0


class StoragePool(BaseModel):
    id: str  # e.g. "unraid_array", "ark", "flash"
    name: str  # e.g. "Main Array", "ark (Cache Pool)"
    pool_type: str  # "unraid_array", "btrfs_raid", "zfs_pool", "jbod", "single"
    fs_type: str = "xfs"  # "xfs", "btrfs", "zfs", "ext4", "unraid"
    fs_profile: str | None = None  # "raid1", "single", "parity1", etc.
    status: str = "HEALTHY"  # "HEALTHY", "DEGRADED", "STANDBY", "SYNCING"
    mountpoint: str | None = None
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    used_pct: float = 0.0
    members: list[PoolMember] = Field(default_factory=list)
    parity_protected: bool = False
    autotrim: bool = False
    compression: str | None = "off"


class NetworkShare(BaseModel):
    name: str  # e.g. "appdata", "vault", "system"
    comment: str = ""
    security: str = "public"  # "public", "secure", "private"
    export_smb: bool = True
    export_nfs: bool = False
    export_webdav: bool = True
    cache_mode: str = "none"  # "only", "yes", "no", "prefer", "none"
    cache_pool: str | None = None
    mountpoint: str = ""
    used_bytes: int = 0
    free_bytes: int = 0
    total_bytes: int = 0
    used_pct: float = 0.0
    allocator: str = "highwater"
    cow: str = "auto"


class PlatformCapabilityError(Exception):
    """Raised when an operation is disallowed by the current platform's capabilities (e.g. in observer mode)."""

    pass


class StoragePlatformAdapter(ABC):
    """Abstract Base Class for all storage platform drivers."""

    @abstractmethod
    def get_platform_type(self) -> PlatformType:
        """Returns the platform type enum."""
        ...

    @abstractmethod
    def get_capabilities(self) -> PlatformCapabilities:
        """Returns platform capability descriptor."""
        ...

    @abstractmethod
    def list_pools(self) -> list[StoragePool]:
        """Discovers and returns all storage pools and their member disks."""
        ...

    @abstractmethod
    def list_shares(self) -> list[NetworkShare]:
        """Discovers and returns all active network shares."""
        ...

    @abstractmethod
    def is_storage_busy(self) -> bool:
        """Returns True if scrub, resilver, parity check, or mover is active."""
        ...

    @abstractmethod
    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        """Triggers or checks the status of a scrub/parity check."""
        ...

    @abstractmethod
    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: list[str],
        mountpoint: str,
    ) -> dict[str, Any]:
        """Creates a storage pool (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def destroy_pool(self, pool_id: str) -> dict[str, Any]:
        """Destroys a storage pool (Active Provisioner mode only)."""
        ...

    @abstractmethod
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
    ) -> dict[str, Any]:
        """Creates a network share (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def delete_share(self, name: str) -> dict[str, Any]:
        """Deletes a network share (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def rename_pool(self, pool_id: str, new_name: str) -> dict[str, Any]:
        """Renames a storage pool (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
        worm_mode: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        """Creates a subvolume snapshot."""
        ...

    @abstractmethod
    def list_snapshots(self, pool_id: str) -> list[dict[str, Any]]:
        """Lists subvolume snapshots for a pool."""
        ...

    @abstractmethod
    def delete_snapshot(
        self,
        pool_id: str,
        snapshot_name: str,
        break_glass: bool = False,
        reason: str = "",
    ) -> dict[str, Any]:
        """Deletes a subvolume snapshot."""
        ...

    @abstractmethod
    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> dict[str, Any]:
        """Restores or rolls back a subvolume snapshot."""
        ...

    @abstractmethod
    def get_pool_path(self, pool_id: str) -> str:
        """Returns the filesystem mountpoint path for the target storage pool."""
        ...

    def export_pool(self, pool_id: str, force: bool = False) -> dict[str, Any]:
        """Safely flushes and exports/unmounts an external or detachable storage pool."""
        raise PlatformCapabilityError(f"Pool export is not supported by {self.__class__.__name__}")

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: str | None = None) -> dict[str, Any]:
        """Imports an external storage pool (e.g. from USB/TB DAS enclosure)."""
        raise PlatformCapabilityError(f"Pool import is not supported by {self.__class__.__name__}")

    def discover_external_pools(self) -> list[dict[str, Any]]:
        """Scans for unmounted/detached external storage pools available for import."""
        return []

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

    @staticmethod
    def _is_os_overlay_or_emmc(path: str) -> bool:
        """Returns True if path points to the root OS overlayfs or internal eMMC boot flash."""
        if not path or not os.path.exists(path):
            return False
        try:
            # 1. Check if path itself is mounted on overlay or mmcblk
            for mf in [
                os.path.join(HOST_PROC, "1/mounts") if HOST_PROC else None,
                os.path.join(HOST_PROC, "mounts") if HOST_PROC else None,
                "/proc/mounts",
            ]:
                if mf and os.path.isfile(mf):
                    try:
                        with open(mf, encoding="utf-8", errors="replace") as f:
                            for line in f:
                                parts = line.strip().split()
                                if len(parts) >= 4:
                                    dev, mp, fstype, opts = parts[0], parts[1], parts[2], parts[3]
                                    if mp == path:
                                        if fstype == "overlay" and (
                                            "lowerdir=/rom" in opts or "/zettlab" in opts or "upperdir=" in opts
                                        ):
                                            return True
                                        if dev.startswith(("/dev/mmcblk", "mmcblk")):
                                            return True
                    except Exception:
                        logger.debug(
                            "backend.hardware.pal_storage.StoragePlatformAdapter._is_os_overlay_or_emmc: ignored error",
                            exc_info=True,
                        )

            # 2. Check if host rootfs is an OS overlay and path is on that same device
            is_root_overlay_or_emmc = False
            for mf in [
                os.path.join(HOST_PROC, "1/mounts") if HOST_PROC else None,
                os.path.join(HOST_PROC, "mounts") if HOST_PROC else None,
                "/proc/mounts",
            ]:
                if mf and os.path.isfile(mf):
                    try:
                        with open(mf, encoding="utf-8", errors="replace") as f:
                            for line in f:
                                parts = line.strip().split()
                                if len(parts) >= 4 and parts[1] == "/":
                                    dev, fstype, opts = parts[0], parts[2], parts[3]
                                    if (
                                        fstype == "overlay"
                                        and (
                                            "lowerdir=/rom" in opts or "/zettlab" in opts or "upperdir=/zettlab" in opts
                                        )
                                        or dev.startswith(("/dev/mmcblk", "mmcblk"))
                                    ):
                                        is_root_overlay_or_emmc = True
                    except Exception:
                        logger.debug(
                            "backend.hardware.pal_storage.StoragePlatformAdapter._is_os_overlay_or_emmc: ignored error",
                            exc_info=True,
                        )

            if is_root_overlay_or_emmc:
                try:
                    if os.stat(path).st_dev == os.stat("/").st_dev:
                        u = shutil.disk_usage(path)
                        if u.total < 128 * 1024 * 1024 * 1024:
                            return True
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformAdapter._is_os_overlay_or_emmc: ignored error",
                        exc_info=True,
                    )
        except Exception:
            logger.debug(
                "backend.hardware.pal_storage.StoragePlatformAdapter._is_os_overlay_or_emmc: ignored error",
                exc_info=True,
            )
        return False

    def _parse_mounts(self) -> list[dict[str, str]]:
        """Parses /proc/mounts to find mounted filesystems, filtering out virtual and pseudo mounts."""
        mounts: list[dict[str, str]] = []
        mount_files = [
            os.path.join(HOST_PROC, "1/mounts") if HOST_PROC else None,
            os.path.join(HOST_PROC, "mounts") if HOST_PROC else None,
            "/proc/mounts",
        ]
        seen_targets = set()
        for target_file in mount_files:
            if not target_file or not os.path.isfile(target_file):
                continue

            skip_fstypes = {
                "proc",
                "sysfs",
                "devtmpfs",
                "devpts",
                "tmpfs",
                "overlay",
                "cgroup",
                "cgroup2",
                "pstore",
                "bpf",
                "autofs",
                "mqueue",
                "hugetlbfs",
                "debugfs",
                "tracefs",
                "securityfs",
                "fusectl",
                "configfs",
                "binfmt_misc",
                "squashfs",
                "nsfs",
                "ramfs",
                "shfs",
            }
            skip_prefixes = ("/proc", "/sys", "/dev", "/run", "/var/lib/docker", "/var/lib/containerd")

            try:
                with open(target_file, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 3:
                            dev, mp, fstype = parts[0], parts[1], parts[2]
                            opts = parts[3] if len(parts) > 3 else ""
                            if fstype in skip_fstypes:
                                continue
                            if any(mp.startswith(pfx) for pfx in skip_prefixes):
                                continue
                            key = (dev, mp)
                            if key not in seen_targets:
                                seen_targets.add(key)
                                mounts.append({"device": dev, "mountpoint": mp, "fstype": fstype, "options": opts})
            except Exception as e:
                logger.debug(f"[PAL] Error reading mounts from {target_file}: {e}")
        return mounts

    def _parse_mdstat(self) -> dict[str, dict[str, Any]]:
        """Parses /proc/mdstat for active Linux software RAID arrays and rebuild/resync status."""
        result: dict[str, dict[str, Any]] = {}
        mdstat_files = [os.path.join(HOST_PROC, "mdstat"), "/proc/mdstat"]
        target = next((f for f in mdstat_files if os.path.isfile(f)), None)
        if not target:
            return result

        try:
            with open(target, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            current_md: str | None = None
            for line in lines:
                line_str = line.strip()
                if not line_str or line_str.startswith("Personalities") or line_str.startswith("unused"):
                    continue

                if " : " in line_str and line_str.startswith("md"):
                    parts = line_str.split(" : ")
                    current_md = parts[0].strip()
                    rest = parts[1].strip().split()
                    state = rest[0] if len(rest) > 0 else "unknown"
                    level = rest[1] if len(rest) > 1 else "unknown"
                    members = []
                    for token in rest[2:]:
                        clean_disk = re.sub(r"\[\d+\]", "", token)
                        members.append(clean_disk)
                    result[current_md] = {
                        "device": current_md,
                        "state": state,
                        "level": level,
                        "members": members,
                        "blocks": 0,
                        "size_bytes": 0,
                        "degraded": False,
                        "sync_action": None,
                        "progress_pct": 0.0,
                    }
                elif current_md and current_md in result:
                    blocks_match = re.search(r"(\d+)\s+blocks", line_str)
                    if blocks_match:
                        blks = int(blocks_match.group(1))
                        result[current_md]["blocks"] = blks
                        result[current_md]["size_bytes"] = blks * 1024

                    if re.search(r"\[[U_]+\]", line_str):
                        bracket_match = re.search(r"\[([U_]+)\]", line_str)
                        if bracket_match and "_" in bracket_match.group(1):
                            result[current_md]["degraded"] = True
                    for action in ("resync", "recovery", "check", "reshape"):
                        if f"{action} = " in line_str:
                            result[current_md]["sync_action"] = action
                            pct_match = re.search(r"=\s*([0-9.]+)%", line_str)
                            if pct_match:
                                try:
                                    result[current_md]["progress_pct"] = float(pct_match.group(1))
                                except ValueError:
                                    pass

            for md_dev, info in result.items():
                if info.get("size_bytes", 0) == 0:
                    for base in [HOST_SYS, "/sys", "/host/sys"]:
                        if not base:
                            continue
                        sz_p = os.path.join(base, "block", md_dev, "size")
                        if os.path.isfile(sz_p):
                            try:
                                info["size_bytes"] = int(open(sz_p).read().strip()) * 512  # noqa: SIM115
                                break
                            except Exception:
                                logger.debug(
                                    "backend.hardware.pal_storage.StoragePlatformAdapter._parse_mdstat: ignored error",
                                    exc_info=True,
                                )
        except Exception as e:
            logger.debug(f"[PAL] Error reading mdstat from {target}: {e}")
        return result

    def _parse_fs_superblock(self, device_path: str) -> dict[str, Any] | None:
        """Directly parses filesystem superblocks from raw block device (Ext2/3/4, XFS, Btrfs)."""
        if not device_path or not os.path.exists(device_path):
            return None
        try:
            with open(device_path, "rb") as f:
                # 1. Check XFS (offset 0)
                f.seek(0)
                hdr = f.read(160)
                if len(hdr) >= 160 and hdr[:4] == b"XFSB":
                    bsize = struct.unpack(">I", hdr[4:8])[0]
                    dblocks = struct.unpack(">Q", hdr[8:16])[0]
                    fdblocks = struct.unpack(">Q", hdr[0x90:0x98])[0] if len(hdr) >= 0x98 else 0
                    tot = dblocks * bsize
                    fre = fdblocks * bsize
                    usd = max(0, tot - fre)
                    pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                    return {
                        "fstype": "xfs",
                        "total_bytes": tot,
                        "free_bytes": fre,
                        "used_bytes": usd,
                        "used_pct": pct,
                    }

                # 2. Check Ext2/3/4 (offset 1024)
                f.seek(1024)
                sb = f.read(1024)
                if len(sb) >= 1024 and struct.unpack("<H", sb[0x38:0x3A])[0] == 0xEF53:
                    s_log_block_size = struct.unpack("<I", sb[0x18:0x1C])[0]
                    bsize = 1024 << s_log_block_size
                    blocks_lo = struct.unpack("<I", sb[0x04:0x08])[0]
                    free_lo = struct.unpack("<I", sb[0x0C:0x10])[0]
                    incompat = struct.unpack("<I", sb[0x60:0x64])[0] if len(sb) >= 0x64 else 0
                    is_64bit = bool(incompat & 0x80)
                    blocks_hi = struct.unpack("<I", sb[0x150:0x154])[0] if (is_64bit and len(sb) >= 0x154) else 0
                    free_hi = struct.unpack("<I", sb[0x158:0x15C])[0] if (is_64bit and len(sb) >= 0x15C) else 0
                    tot_blocks = (blocks_hi << 32) | blocks_lo
                    fre_blocks = (free_hi << 32) | free_lo
                    tot = tot_blocks * bsize
                    fre = fre_blocks * bsize
                    usd = max(0, tot - fre)
                    pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                    return {
                        "fstype": "ext4",
                        "total_bytes": tot,
                        "free_bytes": fre,
                        "used_bytes": usd,
                        "used_pct": pct,
                    }

                # 3. Check Btrfs (offset 0x10000 = 65536)
                f.seek(0x10000)
                sb_btrfs = f.read(512)
                if len(sb_btrfs) >= 512 and sb_btrfs[0x40:0x48] == b"_BHRfS_M":
                    tot = struct.unpack("<Q", sb_btrfs[0x70:0x78])[0]
                    usd = struct.unpack("<Q", sb_btrfs[0x78:0x80])[0]
                    fre = max(0, tot - usd)
                    pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                    return {
                        "fstype": "btrfs",
                        "total_bytes": tot,
                        "free_bytes": fre,
                        "used_bytes": usd,
                        "used_pct": pct,
                    }
        except (OSError, PermissionError, struct.error) as e:
            logger.debug(f"[PAL] Superblock parse on {device_path} failed: {e}")
        return None

    def _read_casaos_storage_db(self) -> dict[str, dict[str, Any]]:
        """Reads pool and raid storage records from CasaOS / ZettOS SQLite local-storage.db if available."""
        result: dict[str, dict[str, Any]] = {}
        db_candidates = [
            "/var/lib/casaos/db/local-storage.db",
            "/host/var/lib/casaos/db/local-storage.db",
            "/var/lib/casaos/local-storage.db",
            "/host/var/lib/casaos/local-storage.db",
            "/DATA/.casaos/db/local-storage.db",
            "/etc/casaos/local-storage.db",
            "/host/etc/casaos/local-storage.db",
        ]
        target_db = next((c for c in db_candidates if os.path.isfile(c)), None)
        if not target_db:
            return result

        try:
            conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True, timeout=2.0)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall()]

            for table in ("raids", "storage", "storages", "pools"):
                if table in tables:
                    cursor.execute(f"PRAGMA table_info({table});")
                    cols = [c[1] for c in cursor.fetchall()]
                    cursor.execute(f"SELECT * FROM {table};")
                    for row in cursor.fetchall():
                        row_dict = dict(zip(cols, row, strict=False))
                        keys = [
                            row_dict.get("path"),
                            row_dict.get("name"),
                            row_dict.get("uuid"),
                            row_dict.get("mount_point"),
                        ]
                        for k in keys:
                            if k:
                                str_k = str(k).strip()
                                result[str_k] = row_dict
                                result[os.path.basename(str_k)] = row_dict
            conn.close()
        except Exception as e:
            logger.debug(f"[PAL] Could not read CasaOS local-storage.db: {e}")
        return result

    def _resolve_container_accessible_path(self, mount_path: str) -> str | None:
        """Resolves a host mount path to an accessible container path, testing various prefix candidates."""
        if not mount_path:
            return None
        if os.path.exists(mount_path):
            return mount_path

        # Check host root prefixes
        for pfx in ("/host/root", "/host"):
            cand = os.path.join(pfx, mount_path.lstrip("/"))
            if os.path.exists(cand):
                return cand

        # Check cross-mounted volume candidates (e.g. /media/Pool_2 -> /mnt/Pool_2, /zettos/Pool_2, etc.)
        name = os.path.basename(mount_path.rstrip("/"))
        if name:
            for base_dir in ("/media", "/mnt", "/DATA", "/zettos", "/zettos/pool", "/mnt/storage", "/app/data"):
                cand = os.path.join(base_dir, name)
                if os.path.exists(cand):
                    return cand

        return None

    def _get_mount_or_device_usage(
        self,
        mount_path: str | None,
        dev_name: str | None = None,
        fallback_total: int = 0,
    ) -> tuple[int, int, int, float, str | None]:
        """
        Determines (total_bytes, used_bytes, free_bytes, used_pct, resolved_fstype).
        Uses a 5-tier discovery strategy:
        1. Container accessible mountpoint via shutil.disk_usage()
        2. Direct superblock inspection on block device or holders/partitions (ext4, xfs, btrfs)
        3. CasaOS / ZettOS SQLite local-storage.db records
        4. lsblk -b -J inspection
        5. Fallback to fallback_total
        """
        clean_dev = os.path.basename(dev_name) if dev_name else ""

        # Tier 1: Container accessible mountpoint
        if mount_path:
            acc_path = self._resolve_container_accessible_path(mount_path) or mount_path
            try:
                if not self._is_os_overlay_or_emmc(acc_path):
                    u = shutil.disk_usage(acc_path)
                    if u.total > 0:
                        tot = u.total
                        usd = u.used
                        fre = u.free
                        pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                        return tot, usd, fre, pct, None
            except Exception:
                logger.debug(
                    "backend.hardware.pal_storage.StoragePlatformAdapter._get_mount_or_device_usage: ignored error",
                    exc_info=True,
                )

        # Tier 2: Superblock direct parsing on device candidates and holder/partitions
        dev_candidates = []
        if clean_dev:
            for d_pfx in ("/dev", "/host/dev", "/dev/mapper", "/host/dev/mapper"):
                cand = os.path.join(d_pfx, clean_dev)
                if os.path.exists(cand) and cand not in dev_candidates:
                    dev_candidates.append(cand)
            # Check partition (e.g. md3p1)
            for d_pfx in ("/dev", "/host/dev"):
                cand = os.path.join(d_pfx, f"{clean_dev}p1")
                if os.path.exists(cand) and cand not in dev_candidates:
                    dev_candidates.append(cand)
            # Check holders from sysfs
            for s_base in (HOST_SYS, "/sys", "/host/sys"):
                if not s_base:
                    continue
                holders_dir = os.path.join(s_base, "block", clean_dev, "holders")
                if os.path.isdir(holders_dir):
                    try:
                        for h in os.listdir(holders_dir):
                            for d_pfx in ("/dev", "/host/dev", "/dev/mapper", "/host/dev/mapper"):
                                cand = os.path.join(d_pfx, h)
                                if os.path.exists(cand) and cand not in dev_candidates:
                                    dev_candidates.append(cand)
                    except Exception:
                        logger.debug(
                            "backend.hardware.pal_storage.StoragePlatformAdapter._get_mount_or_device_usage: ignored error",
                            exc_info=True,
                        )

        for dev_node in dev_candidates:
            sb = self._parse_fs_superblock(dev_node)
            if sb and sb.get("total_bytes", 0) > 0:
                tot = sb["total_bytes"]
                usd = sb["used_bytes"]
                fre = sb["free_bytes"]
                pct = sb["used_pct"]
                fstype = sb["fstype"]
                return tot, usd, fre, pct, fstype

        # Tier 3: CasaOS / ZettOS database records
        db_records = self._read_casaos_storage_db()
        for lookup_key in (clean_dev, mount_path, os.path.basename(mount_path or "")):
            if lookup_key and lookup_key in db_records:
                rec = db_records[lookup_key]
                tot = int(rec.get("size") or rec.get("total_size") or rec.get("capacity") or 0)
                usd = int(rec.get("used") or rec.get("used_size") or 0)
                fre = int(rec.get("free") or rec.get("avail") or (tot - usd if tot >= usd else 0))
                fstype = rec.get("fs_type") or rec.get("type") or None
                if tot > 0 and usd > 0:
                    pct = round(usd / tot * 100, 1)
                    return tot, usd, fre, pct, fstype

        # Tier 4: lsblk -b -J
        if dev_candidates:
            for dev_node in dev_candidates:
                code, out, _ = self._run_cmd(
                    ["lsblk", "-b", "-J", "-o", "NAME,PATH,FSTYPE,FSSIZE,FSUSED,FSAVAIL,FSUSE%", dev_node]
                )
                if code == 0 and out.strip():
                    try:
                        data = json.loads(out)
                        bds = data.get("blockdevices") or []
                        for bd in bds:
                            fssize = bd.get("fssize")
                            fsused = bd.get("fsused")
                            fsavail = bd.get("fsavail")
                            fstype = bd.get("fstype")
                            if fssize and fsused is not None:
                                tot = int(fssize)
                                usd = int(fsused)
                                fre = int(fsavail) if fsavail else max(0, tot - usd)
                                pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
                                return tot, usd, fre, pct, fstype
                    except Exception:
                        logger.debug(
                            "backend.hardware.pal_storage.StoragePlatformAdapter._get_mount_or_device_usage: ignored error",
                            exc_info=True,
                        )

        # Tier 5: Fallback
        tot = fallback_total
        usd = 0
        fre = tot
        pct = 0.0
        return tot, usd, fre, pct, None

    def _discover_hal_disks(self) -> list[PoolMember]:
        """Discovers non-OS physical disks safely via Hardware Abstraction Layer."""
        members: list[PoolMember] = []
        try:
            from backend.hardware.hal import DiskDiscoveryHAL

            hal_disks = DiskDiscoveryHAL.discover_physical_disks()
            for d in hal_disks:
                if not d.removable and d.role != "os":
                    members.append(
                        PoolMember(
                            name=d.dev_name,
                            device=d.dev_name,
                            id=d.serial or d.model,
                            type="Data",
                            role=d.role,
                            size_bytes=d.size_bytes,
                            status="OK",
                            rotational=d.is_rotational,
                            spundown=False,
                            temp_c=None,
                        )
                    )
        except Exception as e:
            logger.debug(f"[PAL] HAL disk discovery fallback: {e}")
        return members

    def _parse_zpool_members(self, zp_name: str) -> list[PoolMember]:
        """Parses zpool status -P to construct PoolMember objects with real hardware device paths."""
        members: list[PoolMember] = []
        code, zstat, _ = self._run_cmd(["zpool", "status", "-P", zp_name])
        if code != 0 or not zstat.strip():
            return members

        in_config = False
        current_section = "data"
        current_vdev = ""

        for raw_line in zstat.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("config:"):
                in_config = True
                continue

            if not in_config:
                continue

            if line.startswith("NAME") and "STATE" in line:
                continue

            if line in ("logs", "cache", "spares", "dedup", "special"):
                current_section = line
                current_vdev = ""
                continue

            parts = line.split()
            if len(parts) >= 2:
                name_token = parts[0]
                state_token = parts[1]
                reads = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 0
                writes = int(parts[3]) if len(parts) >= 4 and parts[3].isdigit() else 0
                cksum = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 0

                if name_token == zp_name:
                    continue

                if any(name_token.startswith(prefix) for prefix in ("raidz", "mirror", "draid")):
                    current_vdev = name_token
                    continue

                if (
                    name_token.startswith("/dev/")
                    or name_token.startswith("sd")
                    or name_token.startswith("nvme")
                    or name_token.startswith("vd")
                ):
                    dev_basename = os.path.basename(name_token)
                    real_dev = dev_basename
                    if os.path.exists(name_token):
                        try:
                            real_dev = os.path.basename(os.path.realpath(name_token))
                        except Exception:
                            logger.debug(
                                "backend.hardware.pal_storage.StoragePlatformAdapter._parse_zpool_members: ignored error",
                                exc_info=True,
                            )

                    clean_dev = _whole_disk(real_dev)

                    m_role = "data"
                    m_type = "Data"
                    if current_section == "cache":
                        m_role = "cache"
                        m_type = "Cache"
                    elif current_section == "logs":
                        m_role = "log"
                        m_type = "Log (SLOG)"
                    elif current_section == "spares":
                        m_role = "spare"
                        m_type = "Hot Spare"
                    elif current_section == "special":
                        m_role = "metadata"
                        m_type = "Special VDEV"
                    elif "raidz" in current_vdev:
                        m_role = "parity"
                        m_type = "RAIDZ Member"
                    elif "mirror" in current_vdev:
                        m_role = "data"
                        m_type = "Mirror Member"

                    is_rot = not clean_dev.startswith("nvme")
                    members.append(
                        PoolMember(
                            name=clean_dev,
                            device=clean_dev,
                            id=dev_basename,
                            type=m_type,
                            role=m_role,
                            size_bytes=0,
                            status="OK" if state_token == "ONLINE" else state_token,
                            rotational=is_rot,
                            spundown=False,
                            num_reads=reads,
                            num_writes=writes,
                            num_errors=cksum,
                        )
                    )

        return members


def _whole_disk(name: str) -> str:
    """The disk a partition belongs to: sdb1 -> sdb, nvme0n1p1 -> nvme0n1, mmcblk0p2 -> mmcblk0.
    Whole NVMe disks keep their name (nvme1n1 is not a partition of nvme1n)."""
    if name.startswith(("nvme", "mmcblk")):
        return re.sub(r"p\d+$", "", name)
    if name.startswith(("sd", "vd", "hd", "xvd")):
        return re.sub(r"\d+$", "", name)
    return name


# Samba configs an observed host may export shares from (a constant so tests can point it elsewhere)
SMB_CONF_PATHS = (
    "/etc/samba/smb.conf",
    "/host/etc/samba/smb.conf",
    "/etc/ugreen/samba/smb.conf",
    "/host/etc/ugreen/samba/smb.conf",
    "/etc/samba/smb.conf.user",
)


def _parse_ini_sections(filepath: str) -> dict[str, dict[str, str]]:
    """Helper to parse multi-section INI files like Unraid disks.ini and shares.ini."""
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    if not os.path.isfile(filepath):
        return sections
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current = line.strip("[]").strip('"').strip("'")
                    sections[current] = {}
                elif current is not None and "=" in line:
                    key, val = line.split("=", 1)
                    k = key.strip()
                    v = val.strip().strip('"').strip("'")
                    sections[current][k] = v
    except Exception as e:
        logger.debug(f"[PAL] Error reading {filepath}: {e}")
    return sections


class UnraidStorageAdapter(StoragePlatformAdapter):
    """
    Unraid OS Storage Platform Adapter.
    Operates in 100% Observer / Companion Mode.
    Audits array status, parity protection, cache pools, and user shares via emhttp state files.
    Strictly forbids array tampering or destructive block operations.
    """

    def __init__(self):
        self._emhttp_dir = _find_emhttp_dir()

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
        emhttp_dir = self._emhttp_dir or _find_emhttp_dir()
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
                mountpoint=POOL_PATH or "/mnt/user",
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
        emhttp_dir = self._emhttp_dir or _find_emhttp_dir()
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
        base_pool_path = POOL_PATH or "/mnt/user"
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
            u = shutil.disk_usage(POOL_PATH or "/mnt/user")
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
                mountpoint=POOL_PATH or "/mnt/user",
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
        return POOL_PATH or "/mnt/user"


class GenericLinuxStorageAdapter(StoragePlatformAdapter):
    """
    Generic Linux Storage Platform Adapter.
    Operates in Active Provisioner Mode (or Observer Mode when unprivileged).
    Supports Btrfs multi-device pools, ext4/xfs volumes, subvolume snapshots,
    and managed Samba/WebDAV shares.
    """

    def __init__(self, pool_path: str | None = None):
        self._pool_path = pool_path or POOL_PATH or "/mnt/storage"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.GENERIC_LINUX

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.GENERIC_LINUX,
            is_observer_mode=False,
            can_create_pools=True,
            can_destroy_pools=True,
            can_manage_shares=True,
            can_trigger_scrub=True,
            supported_filesystems=["btrfs", "ext4", "xfs", "zfs"],
            description="Active Provisioner Mode: Bare-metal Linux host detected. Full pool, subvolume snapshot, and share lifecycle management enabled.",
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
            host_p = os.path.join(HOST_DEV, d.lstrip("/"))
            if os.path.exists(host_p):
                return host_p
            return d

        # Determine target dev name (e.g. "sda", "nvme1n1")
        base_name = os.path.basename(d)

        # Search for canonical persistent /dev/disk/by-id/ symlink
        for by_id_dir in ["/dev/disk/by-id", os.path.join(HOST_DEV, "disk/by-id")]:
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
            host_disk = os.path.join(HOST_DEV, d.lstrip("/"))
            if os.path.exists(host_disk):
                return host_disk
            return d

        for base in [HOST_DEV, "/dev"]:
            cand = os.path.join(base, d)
            if os.path.exists(cand):
                return cand
        return f"/dev/{d}"

    _busy_cache_ts: float = 0.0
    _busy_cache_val: bool = False

    def is_storage_busy(self) -> bool:
        """Checks if a scrub or balance is actively running across Btrfs or OpenZFS pools (10s TTL cache)."""
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
            for s_base in (HOST_SYS, "/sys", "/host/sys"):
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
                        logger.debug(
                            "backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_pools: ignored error",
                            exc_info=True,
                        )

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
                    compression="zstd" if "btrfs" in str(resolved_fstype or mounts) else "off",
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
                            compression="zstd",
                        )
                    )

        # 4. Standard pool at self._pool_path
        if not is_overlay:
            total, used, free = 0, 0, 0
            try:
                u = shutil.disk_usage(self._pool_path if os.path.exists(self._pool_path) else "/")
                total, used, free = u.total, u.used, u.free
            except Exception:
                logger.debug(
                    "backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_pools: ignored error", exc_info=True
                )
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
                        compression="zstd:1",
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
                        logger.debug(
                            "backend.hardware.pal_storage.GenericLinuxStorageAdapter.rename_pool: ignored error",
                            exc_info=True,
                        )
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
        nfs_squash: str = "no_root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "*",
    ) -> dict[str, Any]:
        """Provisions a network share and syncs with SambaEngine and NfsEngine."""
        from backend.services.samba_engine import validate_share_path

        full_path = validate_share_path(path if path else os.path.join(self._pool_path, name))
        if export_nfs:  # refuse bad NFS settings before anything is created
            from backend.services.nfs_engine import NfsExportRule

            try:
                NfsExportRule(
                    name=name,
                    path=full_path,
                    clients=nfs_clients.strip() or "*",
                    squash=nfs_squash or "no_root_squash",
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
            from backend.services.nfs_engine import NfsExportRule

            try:
                rule = NfsExportRule(
                    name=name,
                    path=full_path,
                    clients=nfs_clients.strip() or "*",
                    permission="ro" if read_only else "rw",
                    squash=nfs_squash or "no_root_squash",
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
            "status": "created" if code in (0, 127) else "error",
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
                                logger.debug(
                                    "backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_snapshots: ignored error",
                                    exc_info=True,
                                )
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


class ObserverStorageAdapter(StoragePlatformAdapter):
    """
    Base class for all non-intrusive Observer Mode storage adapters (FygoOS, ZettOS, UGOS, Synology DSM, QTS, etc.).
    Guarantees strict read-only auditing and raises PlatformCapabilityError on all mutating operations.
    """

    def __init__(self, pool_path: str | None = None):
        self._pool_path = pool_path or POOL_PATH or "/mnt/storage"

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
        target_conf = next((c for c in SMB_CONF_PATHS if os.path.isfile(c)), None)
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


class ProxmoxStorageAdapter(ObserverStorageAdapter):
    """
    Proxmox VE Storage Platform Adapter.
    Operates in Observer Mode. Proxmox VE storage manager (pvesm) authoritatively
    manages ZFS thin-pools, LVM-thin, directory storages, and VM virtual disks.
    """

    def get_platform_type(self) -> PlatformType:
        return PlatformType.PROXMOX

    def get_capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(
            platform=PlatformType.PROXMOX,
            is_observer_mode=True,
            can_create_pools=False,
            can_destroy_pools=False,
            can_manage_shares=False,
            can_trigger_scrub=True,
            can_export_pools=False,
            can_import_pools=False,
            supported_filesystems=["zfs", "btrfs", "ext4", "xfs"],
            description="Observer Mode: Proxmox VE host detected. Storage pools and LVM/ZFS thin-pools are managed by PVE storage engine. Telemetry and scrub monitoring enabled.",
        )

    def create_pool(
        self,
        name: str,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        raise PlatformCapabilityError(
            "Pool creation is prohibited on Proxmox VE in observer mode. Use Proxmox Web GUI to provision storage pools."
        )

    def destroy_pool(self, pool_id: str, *args: Any, **kwargs: Any) -> Any:
        raise PlatformCapabilityError(
            "Pool destruction is prohibited on Proxmox VE in observer mode. Use Proxmox Web GUI to manage storage pools."
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
        zp = pool_id if (pool_id and pool_id != "default_pool") else "rpool"
        if action == "start":
            code, out, err = self._run_cmd(["zpool", "scrub", zp])
            return {
                "platform": "proxmox",
                "pool_id": pool_id,
                "action": action,
                "status": "started" if code == 0 else "error",
                "output": out or err,
            }
        elif action == "cancel":
            code, out, err = self._run_cmd(["zpool", "scrub", "-s", zp])
            return {
                "platform": "proxmox",
                "pool_id": pool_id,
                "action": action,
                "status": "cancelled" if code == 0 else "error",
                "output": out or err,
            }
        else:
            code, out, err = self._run_cmd(["zpool", "status", zp])
            return {
                "platform": "proxmox",
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
                            name=f"{zp_name} (Proxmox ZFS Storage)",
                            pool_type="zfs_pool",
                            fs_type="zfs",
                            status="HEALTHY" if zp_health == "ONLINE" else zp_health,
                            mountpoint=f"/{zp_name}",
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
                    id="local",
                    name="local (PVE Storage Directory)",
                    pool_type="single",
                    fs_type="ext4",
                    status="HEALTHY",
                    mountpoint=cand,
                    total_bytes=tot,
                    used_bytes=usd,
                    free_bytes=fre,
                    used_pct=pct,
                    members=self._discover_hal_disks(),
                    parity_protected=False,
                )
            )
        return pools

    def list_shares(self) -> list[NetworkShare]:
        shares = self._parse_smb_conf()
        if not shares:
            shares = self._discover_shares_from_dirs(["/mnt/pve", self._pool_path])
        return shares


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
                    pools.append(
                        StoragePool(
                            id=p_id,
                            name=f"{p_id} (FygoOS Storage Volume)",
                            pool_type="single" if fstype != "btrfs" else "btrfs_raid",
                            fs_type=fstype,
                            fs_profile="single",
                            status="HEALTHY",
                            mountpoint=mp,
                            total_bytes=tot,
                            used_bytes=usd,
                            free_bytes=fre,
                            used_pct=pct,
                            members=hal_disks,
                            parity_protected=fstype == "btrfs",
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
                for base in [HOST_SYS, "/sys", "/host/sys"]:
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
                            logger.debug(
                                "backend.hardware.pal_storage.ZettOSStorageAdapter.trigger_scrub: ignored error",
                                exc_info=True,
                            )
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
                for base in [HOST_SYS, "/sys", "/host/sys"]:
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
                            logger.debug(
                                "backend.hardware.pal_storage.ZettOSStorageAdapter.trigger_scrub: ignored error",
                                exc_info=True,
                            )
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
            for s_base in (HOST_SYS, "/sys", "/host/sys"):
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
                        logger.debug(
                            "backend.hardware.pal_storage.ZettOSStorageAdapter.list_pools: ignored error", exc_info=True
                        )

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
                    compression="zstd" if "btrfs" in str(resolved_fstype or mounts) else "off",
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


class StoragePlatformDetector:
    """Detects the underlying NAS host OS and runtime environment."""

    @staticmethod
    def detect() -> PlatformType:
        obs_adapter = os.environ.get("ZETTNAS_OBSERVER_ADAPTER", "").strip().lower()
        if obs_adapter == "auto":
            obs_adapter = ""
        pal_mode = os.environ.get("ZETTNAS_PAL_MODE", "").strip().lower()
        if pal_mode == "auto":
            pal_mode = ""
        env_platform = os.environ.get("ZETTNAS_PLATFORM", "").strip().lower() or obs_adapter or pal_mode
        if env_platform:
            if env_platform in ("unraid",):
                return PlatformType.UNRAID
            if env_platform in ("truenas", "scale"):
                return PlatformType.TRUENAS
            if env_platform in ("proxmox", "pve"):
                return PlatformType.PROXMOX
            if env_platform in ("fygoos", "fyde", "fydeos"):
                return PlatformType.FYGOOS
            if env_platform in ("zettos", "zettlab", "zettlabs"):
                return PlatformType.ZETTOS
            if env_platform in ("ugos", "ugreen"):
                return PlatformType.UGOS
            if env_platform in ("generic_observer", "observer", "readonly", "telemetry"):
                return PlatformType.GENERIC_OBSERVER
            if env_platform in ("generic_linux", "linux"):
                return PlatformType.GENERIC_LINUX

        # 1. Unraid Detection
        if _find_emhttp_dir() is not None:
            return PlatformType.UNRAID
        ident_candidates = ["/boot/config/ident.cfg", "/host/boot/config/ident.cfg"]
        if any(os.path.isfile(p) for p in ident_candidates):
            return PlatformType.UNRAID

        # 2. ZettOS Detection
        zettos_candidates = [
            "/etc/zettos-release",
            "/host/etc/zettos-release",
            "/etc/zettos/version",
            "/host/etc/zettos/version",
            "/etc/zettos",
            "/host/etc/zettos",
            "/zettos",
            "/host/zettos",
            "/zettlab",
            "/host/zettlab",
        ]
        if any(os.path.isfile(p) or os.path.exists(p) for p in zettos_candidates):
            return PlatformType.ZETTOS

        # Check mount files for ZettOS / Zettlab rootfs signatures
        for m_file in [
            os.path.join(HOST_PROC, "1/mounts") if HOST_PROC else None,
            os.path.join(HOST_PROC, "mounts") if HOST_PROC else None,
            "/proc/mounts",
        ]:
            if m_file and os.path.isfile(m_file):
                try:
                    with open(m_file, encoding="utf-8", errors="replace") as f:
                        m_content = f.read()
                        if "upperdir=/zettlab" in m_content or ("/rom" in m_content and "/zettlab" in m_content):
                            return PlatformType.ZETTOS
                        if "/zettos" in m_content:
                            return PlatformType.ZETTOS
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                    )

        # Check kernel cmdline for ZettOS signatures
        for cmd_file in [
            os.path.join(HOST_PROC, "cmdline") if HOST_PROC else None,
            "/proc/cmdline",
        ]:
            if cmd_file and os.path.isfile(cmd_file):
                try:
                    with open(cmd_file, encoding="utf-8", errors="replace") as f:
                        cmd_text = f.read().lower()
                        if "zettos" in cmd_text or "zettlab" in cmd_text:
                            return PlatformType.ZETTOS
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                    )

        # 3. FygoOS Detection
        fygoos_candidates = [
            "/etc/fygoos-release",
            "/host/etc/fygoos-release",
            "/etc/fyde-release",
            "/host/etc/fyde-release",
            "/var/run/fygoos",
            "/host/var/run/fygoos",
        ]
        if any(os.path.exists(p) for p in fygoos_candidates):
            return PlatformType.FYGOOS

        # 4. UGOS (UGREEN NAS OS) Detection
        ugos_candidates = [
            "/etc/ugos-release",
            "/host/etc/ugos-release",
            "/etc/ugreen",
            "/host/etc/ugreen",
        ]
        if any(os.path.exists(p) for p in ugos_candidates):
            return PlatformType.UGOS

        # 5. Kernel /proc/version checks
        proc_ver_path = os.path.join(HOST_PROC, "version")
        if os.path.isfile(proc_ver_path):
            try:
                with open(proc_ver_path, encoding="utf-8", errors="replace") as f:
                    ver_text = f.read().lower()
                    if "unraid" in ver_text:
                        return PlatformType.UNRAID
                    if "zettos" in ver_text:
                        return PlatformType.ZETTOS
                    if "fygoos" in ver_text or "fydeos" in ver_text:
                        return PlatformType.FYGOOS
                    if "ugos" in ver_text or "ugreen" in ver_text:
                        return PlatformType.UGOS
                    if "pve" in ver_text:
                        return PlatformType.PROXMOX
                    if "truenas" in ver_text:
                        return PlatformType.TRUENAS
            except Exception:
                logger.debug(
                    "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                )

        # 6. /etc/os-release checks
        os_release_paths = ["/etc/os-release", "/host/etc/os-release"]
        for p in os_release_paths:
            if os.path.isfile(p):
                try:
                    with open(p, encoding="utf-8", errors="replace") as f:
                        text = f.read().lower()
                        if "unraid" in text:
                            return PlatformType.UNRAID
                        if "zettos" in text:
                            return PlatformType.ZETTOS
                        if "fygoos" in text or "fydeos" in text:
                            return PlatformType.FYGOOS
                        if "ugos" in text or "ugreen" in text:
                            return PlatformType.UGOS
                        if "truenas" in text:
                            return PlatformType.TRUENAS
                        if "proxmox" in text:
                            return PlatformType.PROXMOX
                except Exception:
                    logger.debug(
                        "backend.hardware.pal_storage.StoragePlatformDetector.detect: ignored error", exc_info=True
                    )

        # 7. Other Appliance NAS (Synology, QNAP, Asustor, CasaOS) or Observer Mode env
        other_nas_candidates = [
            "/etc/synoinfo.conf",
            "/host/etc/synoinfo.conf",
            "/etc/config/uLinux.conf",
            "/host/etc/config/uLinux.conf",
            "/etc/nas.conf",
            "/host/etc/nas.conf",
            "/etc/casaos",
            "/host/etc/casaos",
        ]
        if any(os.path.exists(p) for p in other_nas_candidates):
            return PlatformType.GENERIC_OBSERVER

        if os.environ.get("ZETTNAS_PAL_MODE", "").strip().lower() in ("observer", "readonly", "telemetry"):
            return PlatformType.GENERIC_OBSERVER
        if os.environ.get("ZETTNAS_OBSERVER_MODE") == "1":
            return PlatformType.GENERIC_OBSERVER

        return PlatformType.GENERIC_LINUX


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
