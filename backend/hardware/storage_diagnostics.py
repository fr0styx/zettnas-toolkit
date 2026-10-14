"""
Storage Diagnostics Engine for ZettNAS Toolkit.
Collects non-blocking filesystem, disk topology, PAL pools, mounts with ro/rw audit,
I/O diskstats, FreeDesktop RecycleBin audit, Btrfs chunk allocations, ZFS status,
and zero-wake S.M.A.R.T. telemetry with SQLite degradation velocity and executive reports.

CRITICAL INVARIANT:
Never wake sleeping hard drives. Only read cached SMART telemetry, query persistent SQLite
WAL history, or execute smartctl with '-n standby' and exit code 2 handling.
"""

import glob
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from backend.config import HOST_PROC, POOL_PATH, logger
from backend.db import db_session, get_latest_smart_test_result, query_smart_velocity
from backend.hardware.disks import _discover_disks, read_disk_temps_and_io
from backend.hardware.pal_storage import get_storage_platform
from backend.hardware.unraid import read_unraid_status
from backend.state import Z_STATE


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


def _collect_smart_diagnostics(discovered_disks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Queries persistent SQLite SMART history, linear regression velocity, and
    latest self-test executive reports without waking sleeping drive platters.
    """
    smart_map: Dict[str, Any] = {}
    cached_smart = getattr(Z_STATE, "cached_smart_data", {}) or {}
    active_tests = getattr(Z_STATE, "active_smart_tests", {}) or {}

    try:
        with db_session() as conn:
            for d in discovered_disks:
                dev = d.get("dev") or d.get("name")
                if not dev:
                    continue

                cached_temp, cached_health = cached_smart.get(dev, (None, "unknown"))
                is_standby = cached_health == "standby"

                # 1. Latest metrics from smart_history SQLite table
                metrics: Dict[str, Any] = {}
                poh = 0
                try:
                    row = conn.execute(
                        "SELECT * FROM smart_history WHERE dev = ? ORDER BY ts DESC LIMIT 1", (dev,)
                    ).fetchone()
                    if row:
                        metrics = dict(row)
                        poh = metrics.get("power_on_hours", 0) or 0
                except Exception as e:
                    logger.debug(f"[DIAGNOSTICS] smart_history query failed for {dev}: {e}")

                # 2. Linear regression degradation velocity
                velocity: Dict[str, Any] = {}
                try:
                    velocity = query_smart_velocity(dev, conn=conn)
                except Exception as e:
                    logger.debug(f"[DIAGNOSTICS] velocity query failed for {dev}: {e}")

                # 3. Latest self-test executive report
                latest_test = None
                try:
                    latest_test = get_latest_smart_test_result(dev, conn=conn)
                except Exception as e:
                    logger.debug(f"[DIAGNOSTICS] self-test result query failed for {dev}: {e}")

                # 4. In-flight self-test status
                active_test = active_tests.get(dev)

                smart_map[dev] = {
                    "dev": dev,
                    "model": d.get("model", "Unknown"),
                    "serial": d.get("serial", "Unknown"),
                    "is_nvme": d.get("smart_protocol") == "nvme" or dev.startswith("nvme"),
                    "standby": is_standby,
                    "temp_c": cached_temp,
                    "health": cached_health,
                    "power_on_hours": poh,
                    "metrics": {
                        "reallocated_sectors": metrics.get("reallocated_sectors", 0),
                        "pending_sectors": metrics.get("pending_sectors", 0),
                        "offline_uncorrectable": metrics.get("offline_uncorrectable", 0),
                        "crc_errors": metrics.get("crc_errors", 0),
                        "nvme_pct_used": metrics.get("nvme_pct_used"),
                        "nvme_media_errors": metrics.get("nvme_media_errors", 0),
                    },
                    "velocity": velocity,
                    "latest_test_report": latest_test,
                    "active_test": active_test,
                }
    except Exception as e:
        logger.warning(f"[DIAGNOSTICS] Failed to query SMART database records: {e}")

    return smart_map


def get_btrfs_allocation_breakdown(mounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Parses 'btrfs filesystem df' for all mounted Btrfs filesystems to audit
    Data, Metadata, System, and GlobalReserve chunk allocation profiles.
    """
    btrfs_reports = []
    btrfs_mounts = [m for m in mounts if m.get("fstype") == "btrfs"]

    for m in btrfs_mounts:
        target = m.get("mountpoint")
        if not target or not os.path.exists(target):
            continue
        try:
            r = subprocess.run(
                ["btrfs", "filesystem", "df", target],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if r.returncode == 0 and r.stdout:
                parsed_chunks: Dict[str, Any] = {}
                for line in r.stdout.splitlines():
                    parts = line.strip().split(":", 1)
                    if len(parts) == 2:
                        chunk_type = parts[0].strip()
                        details = parts[1].strip()
                        parsed_chunks[chunk_type] = details
                btrfs_reports.append(
                    {
                        "mountpoint": target,
                        "device": m.get("device"),
                        "chunks": parsed_chunks,
                    }
                )
        except Exception:
            pass

    return btrfs_reports


def get_zpool_status_summary() -> Optional[Dict[str, Any]]:
    """
    Queries non-blocking ZFS pool status with strict 2.0s timeout to prevent hangs
    on corrupted or unresponsive OpenZFS pools.
    """
    if not shutil.which("zpool"):
        return None

    try:
        r = subprocess.run(
            ["zpool", "status", "-P"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if r.returncode != 0:
            return {"error": (r.stderr or "zpool status failed").strip()}

        lines = (r.stdout or "").splitlines()
        state = "UNKNOWN"
        scan = "none"
        errors = "none"

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("state:"):
                state = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("scan:"):
                scan = line_str.split(":", 1)[1].strip()
            elif line_str.startswith("errors:"):
                errors = line_str.split(":", 1)[1].strip()

        return {
            "state": state,
            "scan": scan,
            "errors": errors,
            "raw_lines": lines[:60],
        }
    except subprocess.TimeoutExpired:
        return {"error": "Timeout querying zpool status (pool may be hung or degraded)"}
    except Exception as e:
        return {"error": str(e)}


def get_recycle_bin_audit() -> Dict[str, Any]:
    """
    Audits FreeDesktop .trashinfo items and reclaimed space across common storage roots.
    """
    total_items = 0
    total_bytes = 0
    candidate_roots = [
        "/mnt/user/.RecycleBin",
        "/mnt/cache/.RecycleBin",
        os.path.join(POOL_PATH, ".RecycleBin") if POOL_PATH else None,
    ]

    for root in candidate_roots:
        if not root or not os.path.isdir(root):
            continue
        info_dir = os.path.join(root, "info")
        files_dir = os.path.join(root, "files")
        if os.path.isdir(info_dir):
            try:
                trashinfo_files = glob.glob(os.path.join(info_dir, "*.trashinfo"))
                total_items += len(trashinfo_files)
            except Exception:
                pass
        if os.path.isdir(files_dir):
            try:
                for entry in os.scandir(files_dir):
                    if entry.is_file(follow_symlinks=False):
                        total_bytes += entry.stat().st_size
            except Exception:
                pass

    return {
        "total_items": total_items,
        "total_bytes": total_bytes,
        "total_formatted": f"{round(total_bytes / (1024**3), 2)} GB"
        if total_bytes >= 1024**3
        else f"{round(total_bytes / (1024**2), 1)} MB",
    }


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

    # 3. Mounts audit
    mounts = get_mounts_audit()

    # 4. Zero-wake S.M.A.R.T. Telemetry & Regression Velocity
    smart_diagnostics = _collect_smart_diagnostics(discovered)

    # 5. Platform Abstraction Layer (PAL) telemetry & Snapshots
    pal_info: Dict[str, Any] = {"platform": "unknown"}
    snapshots_list: List[Dict[str, Any]] = []
    try:
        adapter = get_storage_platform()
        caps = adapter.get_capabilities().model_dump()
        pools = [p.model_dump() for p in adapter.list_pools()]
        shares = [s.model_dump() for s in adapter.list_shares()]
        for p in pools:
            pid = p.get("id")
            if pid:
                try:
                    snaps = adapter.list_snapshots(pid)
                    snapshots_list.extend([s.model_dump() if hasattr(s, "model_dump") else s for s in snaps])
                except Exception:
                    pass

        pal_info = {
            "capabilities": caps,
            "pools": pools,
            "shares": shares,
            "is_busy": adapter.is_storage_busy(),
        }
    except Exception as e:
        pal_info["error"] = str(e)

    # 6. Unraid appliance status if applicable
    unraid_status = None
    try:
        unraid_status = read_unraid_status()
    except Exception:
        pass

    # 7. Btrfs Chunk Allocations & ZFS Status
    btrfs_alloc = get_btrfs_allocation_breakdown(mounts)
    zfs_status = get_zpool_status_summary()

    # 8. Recycle Bin Audit
    recycle_bin = get_recycle_bin_audit()

    # 9. Diskstats & MD RAID
    diskstats = get_diskstats_telemetry()
    mdstat = get_mdstat_summary()

    # 10. Cached SMART summary (Legacy contract preservation)
    cached_smart = dict(Z_STATE.cached_smart_data) if hasattr(Z_STATE, "cached_smart_data") else {}

    # 11. High-level Executive Summary
    standby_count = sum(1 for d in live_disks if d.get("standby"))
    degraded_disks = [
        dev for dev, s in smart_diagnostics.items() if s.get("health") in ("warning", "failing", "degraded", "error")
    ]
    overall_status = "CRITICAL" if degraded_disks else "HEALTHY"

    elapsed = round(time.time() - t0, 3)
    return {
        "collection_time_seconds": elapsed,
        "executive_summary": {
            "status": overall_status,
            "total_disks": len(discovered),
            "standby_disks": standby_count,
            "active_disks": max(0, len(discovered) - standby_count),
            "degraded_disks": degraded_disks,
            "pools_count": len(pal_info.get("pools", [])),
            "snapshots_count": len(snapshots_list),
            "recycle_bin_bytes": recycle_bin.get("total_bytes", 0),
        },
        "physical_disks_discovered": discovered,
        "live_disk_telemetry": live_disks,
        "smart_diagnostics": smart_diagnostics,
        "pal_storage": pal_info,
        "snapshots": snapshots_list,
        "btrfs_allocation": btrfs_alloc,
        "zfs_status": zfs_status,
        "recycle_bin": recycle_bin,
        "unraid_array": unraid_status,
        "mounts_audit": mounts,
        "diskstats": diskstats,
        "mdstat": mdstat,
        "cached_smart_summary": cached_smart,
        "pool_path_configured": POOL_PATH,
    }
