"""
Storage Diagnostics Engine for ZettNAS Toolkit.
Collects non-blocking filesystem, disk topology, PAL pools, mounts with ro/rw audit,
I/O diskstats, and cached SMART telemetry.

CRITICAL INVARIANT:
Never wake sleeping hard drives. Only read cached SMART telemetry or execute smartctl
with '-n standby' and exit code 2 handling.
"""

import os
import shutil
import time
from typing import Any, Dict, List, Optional

from backend.config import HOST_PROC, POOL_PATH, logger
from backend.state import Z_STATE
from backend.hardware.disks import _discover_disks, read_disk_temps_and_io
from backend.hardware.pal_storage import get_storage_platform
from backend.hardware.unraid import read_unraid_status


def get_mounts_audit() -> List[Dict[str, Any]]:
    """
    Parses /proc/mounts and audits filesystem health, read-only/read-write flags,
    and storage capacity.
    """
    mounts = []
    mounts_file = (
        os.path.join(HOST_PROC, "mounts") if os.path.exists(os.path.join(HOST_PROC, "mounts")) else "/proc/mounts"
    )

    if not os.path.exists(mounts_file):
        return mounts

    ignored_types = {
        "proc",
        "sysfs",
        "cgroup",
        "cgroup2",
        "tmpfs",
        "devtmpfs",
        "devpts",
        "mqueue",
        "securityfs",
        "pstore",
        "autofs",
        "hugetlbfs",
        "debugfs",
        "tracefs",
        "fusectl",
        "configfs",
        "binfmt_misc",
        "nsfs",
        "overlay",
    }

    try:
        with open(mounts_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                dev, target, fstype, opts = parts[0], parts[1], parts[2], parts[3]

                # Filter out pure kernel pseudo-filesystems
                if fstype in ignored_types and not target.startswith(("/mnt", "/media", "/Volumes", "/storage")):
                    continue

                opt_list = opts.split(",")
                is_ro = "ro" in opt_list
                is_rw = "rw" in opt_list

                # Get disk usage if accessible
                usage_info = None
                try:
                    usage = shutil.disk_usage(target)
                    usage_info = {
                        "total_bytes": usage.total,
                        "used_bytes": usage.used,
                        "free_bytes": usage.free,
                        "used_percent": round((usage.used / usage.total * 100), 1) if usage.total > 0 else 0,
                    }
                except (PermissionError, OSError):
                    pass

                mounts.append(
                    {
                        "device": dev,
                        "mountpoint": target,
                        "fstype": fstype,
                        "options": opt_list,
                        "is_read_only": is_ro,
                        "is_read_write": is_rw,
                        "usage": usage_info,
                    }
                )
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] Failed to read mounts: {e}")

    return mounts


def get_diskstats_telemetry() -> List[Dict[str, Any]]:
    """
    Reads /proc/diskstats for raw sector and I/O wait telemetry.
    """
    stats = []
    diskstats_file = (
        os.path.join(HOST_PROC, "diskstats")
        if os.path.exists(os.path.join(HOST_PROC, "diskstats"))
        else "/proc/diskstats"
    )

    if not os.path.exists(diskstats_file):
        return stats

    try:
        with open(diskstats_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 14:
                    dev_name = parts[2]
                    # Filter to physical drives and key md/nvme devices
                    if not (dev_name.startswith(("sd", "nvme", "md", "vd", "xvd"))):
                        continue
                    stats.append(
                        {
                            "device": dev_name,
                            "reads_completed": int(parts[3]),
                            "reads_merged": int(parts[4]),
                            "sectors_read": int(parts[5]),
                            "read_time_ms": int(parts[6]),
                            "writes_completed": int(parts[7]),
                            "writes_merged": int(parts[8]),
                            "sectors_written": int(parts[9]),
                            "write_time_ms": int(parts[10]),
                            "io_in_progress": int(parts[11]),
                            "io_time_ms": int(parts[12]),
                            "weighted_io_time_ms": int(parts[13]),
                        }
                    )
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] Failed to read diskstats: {e}")

    return stats


def get_mdstat_summary() -> Optional[Dict[str, Any]]:
    """
    Reads /proc/mdstat if Linux Software RAID is active.
    """
    mdstat_file = (
        os.path.join(HOST_PROC, "mdstat") if os.path.exists(os.path.join(HOST_PROC, "mdstat")) else "/proc/mdstat"
    )
    if not os.path.exists(mdstat_file):
        return None

    try:
        with open(mdstat_file, "r") as f:
            content = f.read().strip()
        lines = content.splitlines()
        return {
            "raw": lines[:50],
            "active_arrays": [line.split()[0] for line in lines if "active" in line],
        }
    except Exception as e:
        return {"error": str(e)}


def collect_storage_diagnostics() -> Dict[str, Any]:
    """
    Aggregates complete storage diagnostics without waking sleeping drives.
    """
    t0 = time.time()

    # 1. Physical Disks Inventory (Non-blocking discovery)
    discovered = []
    try:
        discovered = _discover_disks()
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] _discover_disks failed: {e}")

    # 2. Fast non-blocking temp & I/O snapshot
    live_disks = []
    try:
        live_disks = read_disk_temps_and_io(allow_sync_poll=False)
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] read_disk_temps_and_io failed: {e}")

    # 3. Platform Abstraction Layer (PAL) telemetry
    pal_info: Dict[str, Any] = {"platform": "unknown"}
    try:
        adapter = get_storage_platform()
        caps = adapter.get_capabilities().model_dump()
        pools = [p.model_dump() for p in adapter.list_pools()]
        shares = [s.model_dump() for s in adapter.list_shares()]
        pal_info = {
            "capabilities": caps,
            "pools": pools,
            "shares": shares,
            "is_busy": adapter.is_storage_busy(),
        }
    except Exception as e:
        pal_info["error"] = str(e)

    # 4. Unraid appliance status if applicable
    unraid_status = None
    try:
        unraid_status = read_unraid_status()
    except Exception:
        pass

    # 5. Mounts audit
    mounts = get_mounts_audit()

    # 6. Diskstats
    diskstats = get_diskstats_telemetry()

    # 7. Linux MD RAID
    mdstat = get_mdstat_summary()

    # 8. Cached SMART summary (Safe - never wake platters)
    cached_smart = dict(Z_STATE.cached_smart_data) if hasattr(Z_STATE, "cached_smart_data") else {}

    elapsed = round(time.time() - t0, 3)
    return {
        "collection_time_seconds": elapsed,
        "physical_disks_discovered": discovered,
        "live_disk_telemetry": live_disks,
        "pal_storage": pal_info,
        "unraid_array": unraid_status,
        "mounts_audit": mounts,
        "diskstats": diskstats,
        "mdstat": mdstat,
        "cached_smart_summary": cached_smart,
        "pool_path_configured": POOL_PATH,
    }
