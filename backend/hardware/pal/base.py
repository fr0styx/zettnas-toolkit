"""Platform types, the adapter interface (StoragePlatformAdapter) and shared helpers.

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
    can_snapshot: bool = True
    storage_tools: dict[str, bool] = Field(default_factory=dict)  # btrfs / zfs / mdadm found (REL-4)
    can_export_pools: bool = True
    can_import_pools: bool = True
    supported_filesystems: list[str] = Field(default_factory=list)
    description: str = ""


def storage_tools() -> dict[str, bool]:
    """Which storage tools this image can run (REL-4: the image may lack btrfs, ZFS or mdadm)."""
    import shutil

    return {name: bool(shutil.which(name)) for name in ("btrfs", "zfs", "zpool", "mdadm")}


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


BTRFS_REDUNDANT = {"raid1", "raid1c3", "raid1c4", "raid10", "raid5", "raid6"}


def btrfs_data_profiles(device: str, sys_roots: tuple[str, ...] | None = None) -> list[str]:
    """The data profiles of the Btrfs filesystem on this device, from /sys/fs/btrfs
    (["single"], ["raid1"]; two while a balance converts). Empty when unknown."""
    dev = os.path.basename(os.path.realpath(device)) if device else ""
    if not dev:
        return []
    for base in sys_roots or (HOST_SYS, "/sys", "/host/sys"):
        root = os.path.join(base or "", "fs", "btrfs")
        if not base or not os.path.isdir(root):
            continue
        for fsid in sorted(os.listdir(root)):
            if not os.path.exists(os.path.join(root, fsid, "devices", dev)):
                continue
            data = os.path.join(root, fsid, "allocation", "data")
            try:
                return sorted(d for d in os.listdir(data) if os.path.isdir(os.path.join(data, d)))
            except OSError:
                return []
    return []


def btrfs_is_redundant(profiles: list[str]) -> bool:
    """Survives a disk failure: every data profile in use keeps copies on other disks
    (dup keeps two copies on the same disk)."""
    return bool(profiles) and all(p in BTRFS_REDUNDANT for p in profiles)


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
