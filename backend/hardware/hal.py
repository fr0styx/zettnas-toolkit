"""
ZettNAS Toolkit - Unified Hardware Abstraction Layer (HAL)
Hardware-Agnostic Physical Disk & Controller Discovery Pipeline.
Eliminates device-name drift and supports SATA, SAS (HBAs), NVMe, and USB UAS bridges.
"""

import json
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.config import HOST_DEV, HOST_SYS, OS_NVME, logger


class PhysicalDiskRecord(BaseModel):
    dev_name: str  # Kernel name: sda, nvme0n1, sdaa
    canonical_id: str  # Stable by-id identifier or fallback
    dev_path: str  # /dev/sda or /host/dev/sda
    by_id_path: Optional[str] = None  # /dev/disk/by-id/ata-WDC_...
    serial: str = "Unknown"
    model: str = "Unknown"
    vendor: str = "Generic"
    wwn: Optional[str] = None
    transport: str = "sata"  # sata, nvme, sas, usb, pci
    controller_driver: str = "generic"  # ahci, mpt3sas, uas, nvme
    is_rotational: bool = True
    size_bytes: int = 0
    size_formatted: str = "0 GB"
    role: str = "data"  # os, data, cache, removable
    enclosure_slot: Optional[int] = None
    smart_protocol: str = "sat"  # sat, nvme, scsi, sntrealtek, sntjmicron, sat,auto
    removable: bool = False
    mountpoints: List[str] = Field(default_factory=list)


class DiskDiscoveryHAL:
    """
    Universal Hardware Abstraction Layer for physical storage controllers & drives.
    Supports AHCI, SAS HBAs (mpt3sas), PCIe NVMe, ASMedia/JMicron multiplexers,
    and USB-to-SATA/NVMe bridges on x86_64, ARM64, and virtualized architectures.
    """

    _CACHE_TTL = 10.0  # seconds
    _cached_disks: Optional[List[PhysicalDiskRecord]] = None
    _last_scan_time: float = 0.0

    @classmethod
    def _resolve_dev_root(cls) -> str:
        return HOST_DEV if os.path.exists(HOST_DEV) else "/dev"

    @classmethod
    def _resolve_sys_root(cls) -> str:
        return HOST_SYS if os.path.exists(HOST_SYS) else "/sys"

    @classmethod
    def _format_size(cls, size_bytes: int) -> str:
        if size_bytes >= 1e12:
            return f"{size_bytes / 1e12:.1f} TB"
        if size_bytes >= 1e9:
            return f"{size_bytes / 1e9:.1f} GB"
        return f"{size_bytes / 1e6:.0f} MB"

    @classmethod
    def _read_by_id_links(cls) -> Dict[str, str]:
        """Maps kernel device name (sda, nvme0n1) to canonical persistent /dev/disk/by-id/ path."""
        by_id_map: Dict[str, str] = {}
        by_id_dir = os.path.join(cls._resolve_dev_root(), "disk", "by-id")
        if not os.path.isdir(by_id_dir):
            return by_id_map

        try:
            for entry in os.listdir(by_id_dir):
                if entry.startswith("wwn-") or "-part" in entry:
                    continue  # Prefer serial/model-based ID over WWN or partition
                full_path = os.path.join(by_id_dir, entry)
                try:
                    target = os.path.basename(os.path.realpath(full_path))
                    # Prefer ATA/NVMe/SCSI prefixed identifiers
                    if target not in by_id_map or entry.startswith(("ata-", "nvme-", "scsi-")):
                        by_id_map[target] = full_path
                except OSError:
                    continue
        except Exception as e:
            logger.debug(f"[DiskDiscoveryHAL] Failed reading by-id links: {e}")
        return by_id_map

    @classmethod
    def _probe_controller_driver(cls, dev_name: str) -> str:
        """Traces sysfs device symlink to determine bus controller driver (ahci, mpt3sas, uas, nvme)."""
        sys_block = os.path.join(cls._resolve_sys_root(), "block", dev_name, "device")
        if not os.path.exists(sys_block):
            return "generic"
        try:
            driver_link = os.path.join(sys_block, "driver")
            if os.path.exists(driver_link):
                drv = os.path.basename(os.path.realpath(driver_link))
                if drv != "sd":
                    return drv

            real_path = os.path.realpath(sys_block)
            parts = real_path.split(os.sep)
            for part in reversed(parts):
                if "mpt3sas" in part or "mptsas" in part:
                    return "mpt3sas"
                if "usb" in part or "uas" in part:
                    return "uas"
                if "nvme" in part:
                    return "nvme"
                if "ahci" in part or "ata" in part:
                    return "ahci"
        except Exception:
            pass
        return "ahci"

    @classmethod
    def _probe_smart_protocol(cls, dev_name: str, transport: str, controller: str) -> str:
        """Determines initial smartctl device protocol flag."""
        if transport == "nvme" or dev_name.startswith("nvme"):
            return "nvme"
        if controller == "mpt3sas" or transport == "sas":
            return "scsi"
        if transport == "usb" or controller == "uas":
            return "sat,auto"
        return "sat"

    @classmethod
    def discover_physical_disks(cls, force: bool = False) -> List[PhysicalDiskRecord]:
        now = time.time()
        if not force and cls._cached_disks is not None and (now - cls._last_scan_time) < cls._CACHE_TTL:
            return cls._cached_disks

        by_id_map = cls._read_by_id_links()
        records: List[PhysicalDiskRecord] = []

        # 1. Execute lsblk -J for comprehensive, structured hardware inspection
        lsblk_cmd = [
            "lsblk",
            "-J",
            "-b",
            "-o",
            "NAME,KNAME,PATH,TYPE,TRAN,SUBSYSTEMS,ROTA,SIZE,MODEL,SERIAL,WWN,VENDOR,REV,MOUNTPOINT,HOTPLUG",
        ]
        lsblk_disks: List[Dict[str, Any]] = []
        try:
            res = subprocess.run(lsblk_cmd, capture_output=True, text=True, timeout=8)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                for item in data.get("blockdevices", []):
                    # Filter for top-level physical disks (exclude partitions, lvm, loops, rom, zram)
                    if item.get("type") in ("disk",) and not item.get("name", "").startswith(("loop", "zram", "ram")):
                        lsblk_disks.append(item)
        except Exception as e:
            logger.debug(f"[DiskDiscoveryHAL] lsblk execution fallback: {e}")

        # 2. Fallback to sysfs if lsblk is unavailable
        if not lsblk_disks:
            block_dir = os.path.join(cls._resolve_sys_root(), "block")
            if os.path.exists(block_dir):
                for name in sorted(os.listdir(block_dir)):
                    # Supports sd[a-z]+ (including sdaa, sdab), nvme[0-9]+n[0-9]+, vd[a-z]+
                    if re.match(r"^(sd[a-z]+|nvme[0-9]+n[0-9]+|vd[a-z]+)$", name):
                        size_file = os.path.join(block_dir, name, "size")
                        sz_bytes = 0
                        if os.path.exists(size_file):
                            try:
                                sz_bytes = int(open(size_file).read().strip()) * 512
                            except Exception:
                                sz_bytes = 0
                        if sz_bytes == 0:
                            continue  # Ignore empty slots / media missing

                        rota_file = os.path.join(block_dir, name, "queue/rotational")
                        is_rot = True
                        if os.path.exists(rota_file):
                            try:
                                is_rot = open(rota_file).read().strip() == "1"
                            except Exception:
                                is_rot = not name.startswith("nvme")
                        lsblk_disks.append(
                            {
                                "name": name,
                                "kname": name,
                                "path": os.path.join(cls._resolve_dev_root(), name),
                                "rota": is_rot,
                                "size": sz_bytes,
                                "tran": "nvme" if name.startswith("nvme") else "sata",
                                "model": f"Drive {name}",
                                "serial": f"SN-{name}",
                                "mountpoint": None,
                            }
                        )

        # 3. Normalize into canonical PhysicalDiskRecord structures
        for d in lsblk_disks:
            kname = d.get("kname") or d.get("name")
            if not kname:
                continue
            kname = os.path.basename(kname)

            dev_path = d.get("path") or os.path.join(cls._resolve_dev_root(), kname)
            by_id_path = by_id_map.get(kname)
            canonical_id = os.path.basename(by_id_path) if by_id_path else kname

            model = (d.get("model") or "Generic Storage").strip()
            serial = (d.get("serial") or "Unknown").strip()
            vendor = (d.get("vendor") or "Generic").strip()
            wwn = d.get("wwn")
            tran = (d.get("tran") or ("nvme" if kname.startswith("nvme") else "sata")).lower().strip()
            controller = cls._probe_controller_driver(kname)
            is_rot = bool(d.get("rota", True))
            sz = int(d.get("size") or 0)
            if sz == 0 and not bool(d.get("hotplug")):
                continue

            # Discover all mountpoints recursively
            mountpoints: List[str] = []
            if d.get("mountpoint"):
                mountpoints.append(d["mountpoint"])
            for child in d.get("children", []):
                if child.get("mountpoint"):
                    mountpoints.append(child["mountpoint"])

            # Role classification
            is_root = any(m in ("/", "/boot", "/boot/efi") for m in mountpoints)
            if is_root or kname == OS_NVME:
                role = "os"
            elif is_rot:
                role = "data"
            else:
                role = "cache"

            smart_proto = cls._probe_smart_protocol(kname, tran, controller)

            record = PhysicalDiskRecord(
                dev_name=kname,
                canonical_id=canonical_id,
                dev_path=dev_path,
                by_id_path=by_id_path,
                serial=serial,
                model=model,
                vendor=vendor,
                wwn=wwn,
                transport=tran,
                controller_driver=controller,
                is_rotational=is_rot,
                size_bytes=sz,
                size_formatted=cls._format_size(sz),
                role=role,
                enclosure_slot=None,
                smart_protocol=smart_proto,
                removable=bool(d.get("hotplug") or False),
                mountpoints=mountpoints,
            )
            records.append(record)

        cls._cached_disks = records
        cls._last_scan_time = now
        return records
