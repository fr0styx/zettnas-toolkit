"""How well this NAS is protected (FEAT-01): its copies outside the box, the newest good one and
where they are, for the Overview; and where a new one could go, for "Protect this NAS".

A copy counts as outside the box when it is on a cloud remote, a USB disk or another NAS (a
network mount, or replication over SSH). A copy on another pool of the same NAS doesn't: a fire,
a theft or a power surge takes both.
"""

import os
import time
from typing import Any

from backend.config import logger

FRESH_SECS = 3 * 86400  # newer than this, a copy is current
USB_ROOT = "/mnt/disks"
NAS_ROOTS = ("/mnt/remotes", "/mnt/addons")


def kind_of(location: str) -> str:
    """ "cloud", "usb", "nas" or "here" for a backup destination."""
    if location.startswith("rclone:"):
        return "cloud"
    if location.startswith(USB_ROOT + "/"):
        return "usb"
    if location.startswith(tuple(r + "/" for r in NAS_ROOTS)):
        return "nas"
    return "here"


def copies() -> list[dict[str, Any]]:
    """Every backup that puts the files outside this NAS, with when it last succeeded."""
    out: list[dict[str, Any]] = []
    try:
        from backend.services.offsite_backup import list_repos

        for r in list_repos():
            kind = kind_of(str(r.get("location") or ""))
            if kind != "here":
                out.append(
                    {
                        "name": r.get("name") or r.get("id"),
                        "kind": kind,
                        "engine": "offsite",
                        "last_ok": r.get("last_backup"),
                    }
                )
    except Exception:
        logger.debug("protection_status: off-site backups unreadable", exc_info=True)
    try:
        from backend.services.backup_engine import get_backup_jobs

        for j in get_backup_jobs():
            if j.get("kind") == "config" or j.get("destination_type") != "remote" or j.get("migrated_to"):
                continue
            out.append({"name": j.get("name"), "kind": "cloud", "engine": "copy", "last_ok": j.get("last_success_at")})
    except Exception:
        logger.debug("protection_status: copy jobs unreadable", exc_info=True)
    try:
        from backend.services.replication_engine import get_replication_engine

        for j in get_replication_engine().list_jobs():
            if j.get("target_type", "local") != "local":
                out.append(
                    {"name": j.get("name"), "kind": "nas", "engine": "replication", "last_ok": j.get("last_success")}
                )
    except Exception:
        logger.debug("protection_status: replication jobs unreadable", exc_info=True)
    return out


def status(now: float | None = None) -> dict[str, Any]:
    """ "good" (a current copy outside the box), "stale" (only older ones) or "none"."""
    now = now or time.time()
    found = copies()
    good = [c for c in found if c.get("last_ok")]
    fresh = [c for c in good if now - float(c["last_ok"]) <= FRESH_SECS]
    level = "good" if fresh else "stale" if found else "none"
    return {
        "level": level,
        "copies": len(fresh),
        "total": len(found),
        "last_good": max((float(c["last_ok"]) for c in good), default=None),
        "where": sorted({c["kind"] for c in fresh}),
        "items": found,
        "recycle_bytes": _recycle_bytes(),
    }


def _recycle_bytes() -> int:
    try:
        from backend.services.recycle_bin import total_bytes

        return total_bytes()
    except Exception:
        logger.debug("protection_status: recycle bin index unreadable", exc_info=True)
        return 0


def _mounted(root: str) -> list[str]:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [p for p in (os.path.join(root, n) for n in names) if os.path.ismount(p)]


def destinations() -> dict[str, list[str]]:
    """Where a new backup could go: USB disks, network mounts and cloud remotes set up here."""
    cloud: list[str] = []
    try:
        from backend.services.rclone_engine import get_rclone_engine

        cloud = [
            str(r.get("name"))
            for r in get_rclone_engine().list_remotes()
            if r.get("name") and not str(r.get("name")).startswith("crypt_")
        ]
    except Exception:
        logger.debug("protection_status: rclone remotes unreadable", exc_info=True)
    return {"usb": _mounted(USB_ROOT), "nas": [p for root in NAS_ROOTS for p in _mounted(root)], "cloud": cloud}
