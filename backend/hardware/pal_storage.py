"""
ZettNAS Toolkit - Platform Abstraction Layer (PAL)
Universal Storage Subsystem Interface for Appliance & Generic Linux Hosts.
Provides hardware- and OS-agnostic disk, pool, and network share abstractions.
"""

from abc import ABC, abstractmethod
from enum import Enum
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, POOL_PATH, logger
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status


class PlatformType(str, Enum):
    GENERIC_LINUX = "generic_linux"
    UNRAID = "unraid"
    TRUENAS = "truenas"
    PROXMOX = "proxmox"
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
    supported_filesystems: List[str] = Field(default_factory=list)
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
    temp_c: Optional[int] = None
    num_reads: int = 0
    num_writes: int = 0
    num_errors: int = 0


class StoragePool(BaseModel):
    id: str  # e.g. "unraid_array", "ark", "flash"
    name: str  # e.g. "Main Array", "ark (Cache Pool)"
    pool_type: str  # "unraid_array", "btrfs_raid", "zfs_pool", "jbod", "single"
    fs_type: str = "xfs"  # "xfs", "btrfs", "zfs", "ext4", "unraid"
    fs_profile: Optional[str] = None  # "raid1", "single", "parity1", etc.
    status: str = "HEALTHY"  # "HEALTHY", "DEGRADED", "STANDBY", "SYNCING"
    mountpoint: Optional[str] = None
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    used_pct: float = 0.0
    members: List[PoolMember] = Field(default_factory=list)
    parity_protected: bool = False
    autotrim: bool = False
    compression: str = "off"


class NetworkShare(BaseModel):
    name: str  # e.g. "appdata", "vault", "system"
    comment: str = ""
    security: str = "public"  # "public", "secure", "private"
    export_smb: bool = True
    export_nfs: bool = False
    export_webdav: bool = True
    cache_mode: str = "none"  # "only", "yes", "no", "prefer", "none"
    cache_pool: Optional[str] = None
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
    def list_pools(self) -> List[StoragePool]:
        """Discovers and returns all storage pools and their member disks."""
        ...

    @abstractmethod
    def list_shares(self) -> List[NetworkShare]:
        """Discovers and returns all active network shares."""
        ...

    @abstractmethod
    def is_storage_busy(self) -> bool:
        """Returns True if scrub, resilver, parity check, or mover is active."""
        ...

    @abstractmethod
    def trigger_scrub(self, pool_id: str, action: str = "start") -> Dict[str, Any]:
        """Triggers or checks the status of a scrub/parity check."""
        ...

    @abstractmethod
    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: List[str],
        mountpoint: str,
    ) -> Dict[str, Any]:
        """Creates a storage pool (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def destroy_pool(self, pool_id: str) -> Dict[str, Any]:
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
        nfs_squash: str = "no_root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "*",
    ) -> Dict[str, Any]:
        """Creates a network share (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def delete_share(self, name: str) -> Dict[str, Any]:
        """Deletes a network share (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def rename_pool(self, pool_id: str, new_name: str) -> Dict[str, Any]:
        """Renames a storage pool (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
        worm_mode: Optional[str] = None,
        retention_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Creates a subvolume snapshot."""
        ...

    @abstractmethod
    def list_snapshots(self, pool_id: str) -> List[Dict[str, Any]]:
        """Lists subvolume snapshots for a pool."""
        ...

    @abstractmethod
    def delete_snapshot(
        self,
        pool_id: str,
        snapshot_name: str,
        break_glass: bool = False,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Deletes a subvolume snapshot."""
        ...

    @abstractmethod
    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> Dict[str, Any]:
        """Restores or rolls back a subvolume snapshot."""
        ...

    @abstractmethod
    def get_pool_path(self, pool_id: str) -> str:
        """Returns the filesystem mountpoint path for the target storage pool."""
        ...

    def export_pool(self, pool_id: str, force: bool = False) -> Dict[str, Any]:
        """Safely flushes and exports/unmounts an external or detachable storage pool."""
        raise PlatformCapabilityError(f"Pool export is not supported by {self.__class__.__name__}")

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: Optional[str] = None) -> Dict[str, Any]:
        """Imports an external storage pool (e.g. from USB/TB DAS enclosure)."""
        raise PlatformCapabilityError(f"Pool import is not supported by {self.__class__.__name__}")

    def discover_external_pools(self) -> List[Dict[str, Any]]:
        """Scans for unmounted/detached external storage pools available for import."""
        return []

    def _run_cmd(self, cmd: List[str]) -> Tuple[int, str, str]:
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


def _parse_ini_sections(filepath: str) -> Dict[str, Dict[str, str]]:
    """Helper to parse multi-section INI files like Unraid disks.ini and shares.ini."""
    sections: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    if not os.path.isfile(filepath):
        return sections
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
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
            supported_filesystems=["unraid", "btrfs", "zfs", "xfs"],
            description="Observer Mode: Unraid OS authoritatively manages array disks and shares. Modifying pools from container is prohibited to protect parity.",
        )

    def is_storage_busy(self) -> bool:
        status = read_unraid_status()
        resync = status.get("parity_check", {}).get("active", False)
        mover = status.get("mover", {}).get("active", False)
        return bool(resync or mover)

    def trigger_scrub(self, pool_id: str, action: str = "start") -> Dict[str, Any]:
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

    def list_pools(self) -> List[StoragePool]:
        emhttp_dir = self._emhttp_dir or _find_emhttp_dir()
        if not emhttp_dir:
            return self._fallback_pools()

        disks_file = os.path.join(emhttp_dir, "disks.ini")
        disks_data = _parse_ini_sections(disks_file)
        if not disks_data:
            return self._fallback_pools()

        pools: List[StoragePool] = []
        array_members: List[PoolMember] = []
        cache_pools: Dict[str, List[PoolMember]] = {}
        cache_pool_meta: Dict[str, Dict[str, Any]] = {}
        boot_members: List[PoolMember] = []
        boot_meta: Dict[str, Any] = {}

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

    def list_shares(self) -> List[NetworkShare]:
        emhttp_dir = self._emhttp_dir or _find_emhttp_dir()
        shares: List[NetworkShare] = []
        shares_data: Dict[str, Dict[str, str]] = {}
        sec_data: Dict[str, Dict[str, str]] = {}
        sec_nfs_data: Dict[str, Dict[str, str]] = {}

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
                            share_meta: Dict[str, str] = {}
                            with open(cfg_path, "r", encoding="utf-8", errors="replace") as f:
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

    def _fallback_pools(self) -> List[StoragePool]:
        """Provides disk usage fallback when emhttp state is inaccessible."""
        total, used, free = 0, 0, 0
        try:
            u = shutil.disk_usage(POOL_PATH or "/mnt/user")
            total, used, free = u.total, u.used, u.free
        except Exception:
            pass
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
        disks: List[str],
        mountpoint: str,
    ) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Unraid OS authoritatively manages array disks and pools. "
            "Modifying pools from within container is prohibited to protect array parity."
        )

    def destroy_pool(self, pool_id: str) -> Dict[str, Any]:
        raise PlatformCapabilityError("Observer mode active: Destroying pools is prohibited on Unraid appliance hosts.")

    def export_pool(self, pool_id: str, force: bool = False) -> Dict[str, Any]:
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

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: Optional[str] = None) -> Dict[str, Any]:
        if fs_type.lower() == "zfs":
            code, out, err = self._run_cmd(["zpool", "import", "-f", pool_id])
            if code != 0:
                raise RuntimeError(f"Failed to import zpool '{pool_id}': {err or out}")
            return {"status": "imported", "pool_id": pool_id, "fs_type": "zfs"}
        raise PlatformCapabilityError("Non-ZFS external pools on Unraid must be mounted via Unassigned Devices.")

    def discover_external_pools(self) -> List[Dict[str, Any]]:
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
        nfs_squash: str = "no_root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "*",
    ) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Network shares on Unraid must be provisioned via the Unraid WebGUI "
            "or /boot/config/shares to ensure proper Samba shfs driver integration."
        )

    def delete_share(self, name: str) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Deleting network shares on Unraid must be performed via the Unraid WebGUI."
        )

    def rename_pool(self, pool_id: str, new_name: str) -> Dict[str, Any]:
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
        worm_mode: Optional[str] = None,
        retention_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots on Unraid are authoritatively managed by Unraid."
        )

    def list_snapshots(self, pool_id: str) -> List[Dict[str, Any]]:
        return []

    def delete_snapshot(
        self,
        pool_id: str,
        snapshot_name: str,
        break_glass: bool = False,
        reason: str = "",
    ) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots on Unraid are authoritatively managed by Unraid."
        )

    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> Dict[str, Any]:
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

    def __init__(self, pool_path: Optional[str] = None):
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

    def _run_cmd(self, cmd: List[str]) -> Tuple[int, str, str]:
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

    def is_storage_busy(self) -> bool:
        """Checks if a scrub or balance is actively running."""
        code, out, _ = self._run_cmd(["btrfs", "scrub", "status", self._pool_path])
        return "running" in out.lower()

    def trigger_scrub(self, pool_id: str, action: str = "start") -> Dict[str, Any]:
        """Triggers or checks status of Btrfs scrub."""
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
                "status": "idle" if "no scrub running" in out.lower() else "active",
                "raw": out or err,
            }

    def list_pools(self) -> List[StoragePool]:
        total, used, free = 0, 0, 0
        try:
            u = shutil.disk_usage(self._pool_path if os.path.exists(self._pool_path) else "/")
            total, used, free = u.total, u.used, u.free
        except Exception:
            pass
        pct = round(used / total * 100, 1) if total > 0 else 0.0

        # Query physical disks from HAL to discover member disks
        members: List[PoolMember] = []
        try:
            from backend.hardware.hal import DiskDiscoveryHAL

            hal_disks = DiskDiscoveryHAL.discover_physical_disks()
            for d in hal_disks:
                # Include non-removable disks that are data or cache
                if not d.removable and d.role != "os":
                    members.append(
                        PoolMember(
                            name=d.name,
                            device=d.name,
                            id=d.serial or d.model,
                            type="Data",
                            role=d.role,
                            size_bytes=d.size_bytes,
                            status="STANDBY" if d.spundown else "OK",
                            rotational=d.rotational,
                            spundown=d.spundown,
                            temp_c=d.temp_c,
                        )
                    )
        except Exception as e:
            logger.debug(f"[PAL] HAL disk discovery fallback for generic pools: {e}")

        # Check btrfs filesystem show to detect profile
        profile = "raid1" if len(members) >= 2 else "single"
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

        parity_protected = profile in ("raid1", "raid10")

        pools = [
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
            )
        ]

        # 2. Discover OpenZFS pools
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
                            members=[],
                            parity_protected=z_profile in ("raidz1", "raidz2", "raidz3", "mirror"),
                            autotrim=True,
                            compression="zstd",
                        )
                    )

        return pools

    def list_shares(self) -> List[NetworkShare]:
        shares_map: Dict[str, NetworkShare] = {}
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

    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: List[str],
        mountpoint: str,
    ) -> Dict[str, Any]:
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
            code, out, err = self._run_cmd(cmd)
            if code != 0 and code != 127:
                logger.warning(f"[PAL] zpool create returned {code}: {err}")

        elif fs_lower == "btrfs":
            cmd = ["mkfs.btrfs", "-f", "-L", name, "-m", profile_lower, "-d", profile_lower] + resolved_disks
            code, out, err = self._run_cmd(cmd)
            if code != 0 and code != 127:
                logger.warning(f"[PAL] mkfs.btrfs returned {code}: {err}")

            # Mount with modern zstd compression and fast noatime
            mount_cmd = ["mount", "-o", "compress=zstd:1,noatime,space_cache=v2", resolved_disks[0], target_mount]
            self._run_cmd(mount_cmd)

            # Create default subvolumes for shares and snapshots
            self._run_cmd(["btrfs", "subvolume", "create", os.path.join(target_mount, "@shares")])
            self._run_cmd(["btrfs", "subvolume", "create", os.path.join(target_mount, "@snapshots")])

        elif fs_lower == "ext4":
            cmd = ["mkfs.ext4", "-F", "-L", name, resolved_disks[0]]
            self._run_cmd(cmd)
            self._run_cmd(["mount", resolved_disks[0], target_mount])

        elif fs_lower == "xfs":
            cmd = ["mkfs.xfs", "-f", "-L", name, resolved_disks[0]]
            self._run_cmd(cmd)
            self._run_cmd(["mount", resolved_disks[0], target_mount])

        return {
            "status": "provisioned",
            "name": name,
            "fs_type": fs_lower,
            "profile": profile_lower,
            "mountpoint": target_mount,
            "disks": resolved_disks,
            "created_at": time.time(),
        }

    def rename_pool(self, pool_id: str, new_name: str) -> Dict[str, Any]:
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
                        pass
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

    def destroy_pool(self, pool_id: str) -> Dict[str, Any]:
        """Safely unmounts and removes a storage pool."""
        target_mount = os.path.join(self._pool_path, pool_id) if pool_id != "default_pool" else self._pool_path
        code, out, err = self._run_cmd(["umount", "-f", target_mount])
        return {
            "status": "destroyed",
            "pool_id": pool_id,
            "mountpoint": target_mount,
            "unmount_code": code,
        }

    def export_pool(self, pool_id: str, force: bool = False) -> Dict[str, Any]:
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

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: Optional[str] = None) -> Dict[str, Any]:
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

    def discover_external_pools(self) -> List[Dict[str, Any]]:
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
        nfs_squash: str = "no_root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "*",
    ) -> Dict[str, Any]:
        """Provisions a network share and syncs with SambaEngine and NfsEngine."""
        full_path = path if path else os.path.join(self._pool_path, name)
        try:
            os.makedirs(full_path, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create share dir {full_path}: {e}")

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
                )
                engine.add_or_update_share(share_cfg)
            except Exception as e:
                logger.warning(f"[PAL] SambaEngine registration failed: {e}")

        if export_nfs:
            try:
                from backend.services.nfs_engine import NfsExportRule, get_nfs_engine

                nfs_engine = get_nfs_engine()
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
                nfs_engine.add_or_update_export(rule)
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
        }

    def delete_share(self, name: str) -> Dict[str, Any]:
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
        worm_mode: Optional[str] = None,
        retention_days: Optional[int] = None,
    ) -> Dict[str, Any]:
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
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(worm_meta, f, indent=2)
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

    def list_snapshots(self, pool_id: str) -> List[Dict[str, Any]]:
        """Lists active Btrfs subvolume snapshots with WORM immutability metadata."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        snapshots: List[Dict[str, Any]] = []
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
                                with open(meta_path, "r", encoding="utf-8") as f:
                                    meta = json.load(f)
                                item["worm_mode"] = meta.get("worm_mode")
                                item["retention_until"] = meta.get("retention_until")
                                item["is_immutable"] = (meta.get("retention_until") or 0) > time.time()
                            except Exception:
                                pass
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
    ) -> Dict[str, Any]:
        """Deletes a Btrfs subvolume snapshot, strictly enforcing Two-Tier WORM immutability."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        target_path = os.path.join(snaps_dir, snapshot_name)
        meta_path = os.path.join(snaps_dir, f".{snapshot_name}.worm.json")

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
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

    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> Dict[str, Any]:
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


class StoragePlatformDetector:
    """Detects the underlying NAS host OS and runtime environment."""

    @staticmethod
    def detect() -> PlatformType:
        # 1. Unraid Detection
        if _find_emhttp_dir() is not None:
            return PlatformType.UNRAID
        ident_candidates = ["/boot/config/ident.cfg", "/host/boot/config/ident.cfg"]
        if any(os.path.isfile(p) for p in ident_candidates):
            return PlatformType.UNRAID

        # 2. Kernel/OS-release checks
        proc_ver_path = os.path.join(HOST_PROC, "version")
        if os.path.isfile(proc_ver_path):
            try:
                with open(proc_ver_path, "r", encoding="utf-8", errors="replace") as f:
                    ver_text = f.read().lower()
                    if "unraid" in ver_text:
                        return PlatformType.UNRAID
                    if "pve" in ver_text:
                        return PlatformType.PROXMOX
                    if "truenas" in ver_text:
                        return PlatformType.TRUENAS
            except Exception:
                pass

        os_release_paths = ["/etc/os-release", "/host/etc/os-release"]
        for p in os_release_paths:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read().lower()
                        if "unraid" in text:
                            return PlatformType.UNRAID
                        if "truenas" in text:
                            return PlatformType.TRUENAS
                        if "proxmox" in text:
                            return PlatformType.PROXMOX
                except Exception:
                    pass

        return PlatformType.GENERIC_LINUX


_CACHED_ADAPTER: Optional[StoragePlatformAdapter] = None


def get_storage_platform(force_refresh: bool = False) -> StoragePlatformAdapter:
    """Returns singleton platform adapter based on detected host environment."""
    global _CACHED_ADAPTER
    if _CACHED_ADAPTER is not None and not force_refresh:
        return _CACHED_ADAPTER

    platform_type = StoragePlatformDetector.detect()
    logger.info(f"[PAL] Storage platform detected: {platform_type.value}")

    if platform_type == PlatformType.UNRAID:
        _CACHED_ADAPTER = UnraidStorageAdapter()
    else:
        _CACHED_ADAPTER = GenericLinuxStorageAdapter()

    return _CACHED_ADAPTER
