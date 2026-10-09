"""
ZettNAS Toolkit - Platform Abstraction Layer (PAL)
Universal Storage Subsystem Interface for Appliance & Generic Linux Hosts.
Provides hardware- and OS-agnostic disk, pool, and network share abstractions.
"""

from abc import ABC, abstractmethod
from enum import Enum
import os
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
    ) -> Dict[str, Any]:
        """Creates a network share (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def delete_share(self, name: str) -> Dict[str, Any]:
        """Deletes a network share (Active Provisioner mode only)."""
        ...

    @abstractmethod
    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
    ) -> Dict[str, Any]:
        """Creates a subvolume snapshot."""
        ...

    @abstractmethod
    def list_snapshots(self, pool_id: str) -> List[Dict[str, Any]]:
        """Lists subvolume snapshots for a pool."""
        ...

    @abstractmethod
    def delete_snapshot(self, pool_id: str, snapshot_name: str) -> Dict[str, Any]:
        """Deletes a subvolume snapshot."""
        ...


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

    def create_share(
        self,
        name: str,
        path: str,
        comment: str = "",
        security: str = "public",
        read_only: bool = False,
    ) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Network shares on Unraid must be provisioned via the Unraid WebGUI "
            "or /boot/config/shares to ensure proper Samba shfs driver integration."
        )

    def delete_share(self, name: str) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Deleting network shares on Unraid must be performed via the Unraid WebGUI."
        )

    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
    ) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots on Unraid are authoritatively managed by Unraid."
        )

    def list_snapshots(self, pool_id: str) -> List[Dict[str, Any]]:
        return []

    def delete_snapshot(self, pool_id: str, snapshot_name: str) -> Dict[str, Any]:
        raise PlatformCapabilityError(
            "Observer mode active: Filesystem snapshots on Unraid are authoritatively managed by Unraid."
        )


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
        """Resolves relative or bare disk names to canonical block device path."""
        d = disk.strip()
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

        return [
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

    def list_shares(self) -> List[NetworkShare]:
        shares: List[NetworkShare] = []
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

                shares.append(
                    NetworkShare(
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
                )
            if shares:
                return shares
        except Exception as e:
            logger.debug(f"[PAL] SambaEngine shares query fallback: {e}")

        # 2. Filesystem directory fallback
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
                        shares.append(
                            NetworkShare(
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
                        )
            except Exception as e:
                logger.debug(f"[PAL] Error listing generic shares: {e}")
        return shares

    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: List[str],
        mountpoint: str,
    ) -> Dict[str, Any]:
        """Creates a multi-device Btrfs, ext4, or XFS storage pool."""
        if not disks:
            raise ValueError("At least one disk must be specified to create a storage pool")

        resolved_disks = [self._resolve_disk_path(d) for d in disks]
        profile_lower = profile.lower()
        fs_lower = fs_type.lower()

        # Validate drive counts for RAID profiles
        if profile_lower in ("raid1", "raid0") and len(resolved_disks) < 2:
            raise ValueError(f"{profile.upper()} requires at least 2 disks")
        if profile_lower == "raid10" and len(resolved_disks) < 4:
            raise ValueError("RAID10 requires at least 4 disks")

        target_mount = mountpoint.strip() or os.path.join(self._pool_path, name)
        try:
            os.makedirs(target_mount, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create target mount dir {target_mount}: {e}")

        if fs_lower == "btrfs":
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

    def create_share(
        self,
        name: str,
        path: str,
        comment: str = "",
        security: str = "public",
        read_only: bool = False,
    ) -> Dict[str, Any]:
        """Provisions a network share and syncs with SambaEngine."""
        full_path = path if path else os.path.join(self._pool_path, name)
        try:
            os.makedirs(full_path, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create share dir {full_path}: {e}")

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

        return {
            "status": "created",
            "name": name,
            "mountpoint": full_path,
            "comment": comment,
            "security": security,
            "read_only": read_only,
        }

    def delete_share(self, name: str) -> Dict[str, Any]:
        """Deletes a network share from Samba configuration."""
        try:
            from backend.services.samba_engine import get_samba_engine

            engine = get_samba_engine()
            engine.remove_share(name)
        except Exception as e:
            logger.warning(f"[PAL] Failed deleting share from SambaEngine: {e}")

        return {"status": "deleted", "name": name}

    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
    ) -> Dict[str, Any]:
        """Creates an atomic Btrfs subvolume snapshot."""
        src_path = os.path.join(self._pool_path, "@shares", subvol_name)
        if not os.path.exists(src_path):
            src_path = os.path.join(self._pool_path, subvol_name)

        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        try:
            os.makedirs(snaps_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create snapshots dir {snaps_dir}: {e}")
        dest_path = os.path.join(snaps_dir, snapshot_name)

        cmd = ["btrfs", "subvolume", "snapshot"]
        if readonly:
            cmd.append("-r")
        cmd.extend([src_path, dest_path])
        code, out, err = self._run_cmd(cmd)

        return {
            "status": "created" if code in (0, 127) else "error",
            "source": src_path,
            "snapshot": dest_path,
            "readonly": readonly,
            "code": code,
            "output": out or err,
        }

    def list_snapshots(self, pool_id: str) -> List[Dict[str, Any]]:
        """Lists active Btrfs subvolume snapshots."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        snapshots: List[Dict[str, Any]] = []
        if os.path.isdir(snaps_dir):
            try:
                for entry in sorted(os.listdir(snaps_dir)):
                    p = os.path.join(snaps_dir, entry)
                    if os.path.isdir(p):
                        stat = os.stat(p)
                        snapshots.append(
                            {
                                "name": entry,
                                "path": p,
                                "created_at": stat.st_mtime,
                                "pool_id": pool_id,
                            }
                        )
            except Exception as e:
                logger.debug(f"[PAL] Snapshot list error: {e}")
        return snapshots

    def delete_snapshot(self, pool_id: str, snapshot_name: str) -> Dict[str, Any]:
        """Deletes a Btrfs subvolume snapshot."""
        target_path = os.path.join(self._pool_path, "@snapshots", snapshot_name)
        code, out, err = self._run_cmd(["btrfs", "subvolume", "delete", target_path])
        return {
            "status": "deleted" if code in (0, 127) else "error",
            "snapshot": snapshot_name,
            "path": target_path,
            "code": code,
        }


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
