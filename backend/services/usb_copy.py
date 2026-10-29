"""USB disks: one-touch photo import and "back up the NAS to this disk" (FEAT-07).

When a USB disk appears under /mnt/disks, ZettNAS offers what fits it: run the off-site
backups that live on it (or start them by itself when that is turned on), and import the
photos and videos of a camera or phone disk (its DCIM folder) into dated folders with the same
verified copy the card reader uses. New disks are noticed from the mount table alone, so a
sleeping disk is never touched; a disk's contents are only looked at once it is offered or
listed, when it has just been plugged in or someone asked.
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json
from backend.services.protection_status import USB_ROOT

SETTINGS_FILE = os.path.join(DATA_DIR, "usb_copy.json")
DEFAULTS = {"offer": True, "auto_backup": False}
MOUNTS = "/proc/self/mounts"

_SEEN: set[str] | None = None  # None until the first look, so disks already there aren't offered


def settings() -> dict[str, Any]:
    return {**DEFAULTS, **{k: bool(v) for k, v in (read_json(SETTINGS_FILE, {}) or {}).items() if k in DEFAULTS}}


def save_settings(**changes: Any) -> dict[str, Any]:
    cur = settings()
    cur.update({k: bool(v) for k, v in changes.items() if k in DEFAULTS and v is not None})
    atomic_write_json(SETTINGS_FILE, cur)
    return cur


def mounted(root: str | None = None, mounts: str | None = None) -> list[str]:
    """Mount points under root, from the mount table (no disk is touched)."""
    base = (root or USB_ROOT).rstrip("/") + "/"
    try:
        with open(mounts or MOUNTS, encoding="utf-8") as f:
            points = [line.split()[1].replace("\\040", " ") for line in f if len(line.split()) > 1]
    except OSError:
        return []
    return sorted({p for p in points if p.startswith(base) and "/" not in p[len(base) :]})


def _backups_on(path: str) -> list[dict[str, Any]]:
    from backend.services import offsite_backup

    base = path.rstrip("/") + "/"
    return [
        {"id": r["id"], "name": r.get("name") or r["id"]}
        for r in offsite_backup.list_repos()
        if (r.get("location") or "") == path or (r.get("location") or "").startswith(base)
    ]


def describe(path: str) -> dict[str, Any]:
    """One disk: its name, space, backups that live on it, and whether it holds camera media."""
    try:
        du = shutil.disk_usage(path)
        total, free = du.total, du.free
    except OSError:
        total = free = 0
    return {
        "name": os.path.basename(path),
        "path": path,
        "total_bytes": total,
        "free_bytes": free,
        "media": os.path.isdir(os.path.join(path, "DCIM")),
        "backups": _backups_on(path),
    }


def disks() -> list[dict[str, Any]]:
    return [describe(p) for p in mounted()]


def find(path: str) -> dict[str, Any]:
    """A mounted USB disk by its path; KeyError when it isn't one."""
    if path not in mounted():
        raise KeyError(f"No USB disk is mounted at {path}.")
    return describe(path)


def start_backups(path: str, owner: str | None = None) -> list[str]:
    """Starts every off-site backup that lives on the disk; returns their ids."""
    from backend.services import offsite_backup

    disk = find(path)
    if not disk["backups"]:
        raise LookupError("No backup goes to this disk yet. Set one up with Protect this NAS → A USB disk.")
    started = []
    for b in disk["backups"]:
        try:
            offsite_backup.start_backup(b["id"], owner=owner)
            started.append(b["id"])
        except offsite_backup.BusyError:
            logger.info("[USB] %s is already running", b["id"])
    return started


def _offer(disk: dict[str, Any], z_state: Any, notify: Any) -> None:
    what = []
    if disk["backups"]:
        what.append("back up the NAS to it")
    if disk["media"]:
        what.append("import its photos")
    if not what:
        return
    z_state.pending_usb = {**disk, "ts": time.time()}
    z_state.ui_wake.set()
    notify(
        {
            "type": "media",
            "title": "USB disk connected",
            "message": f"{disk['name']}: {' or '.join(what)}? Open ZettNAS to choose.",
            "level": "info",
        }
    )


def tick(z_state: Any = None, notify: Any = None) -> list[str]:
    """Called once a minute: offers what fits each newly plugged-in USB disk. Returns their paths."""
    global _SEEN
    now = set(mounted())
    if _SEEN is None:
        _SEEN = now
        return []
    new = sorted(now - _SEEN)
    _SEEN = now
    if z_state is not None and getattr(z_state, "pending_usb", None) and z_state.pending_usb.get("path") not in now:
        z_state.pending_usb = None  # the offered disk was unplugged
        z_state.ui_wake.set()
    if not new:
        return []
    if z_state is None:
        from backend.state import Z_STATE as z_state
    if notify is None:
        from backend.services.notifications import send_notification as notify
    cfg = settings()
    for path in new:
        disk = describe(path)
        logger.info("[USB] %s connected (%d backups, media: %s)", disk["name"], len(disk["backups"]), disk["media"])
        if cfg["auto_backup"] and disk["backups"]:
            ids = start_backups(path)
            notify(
                {
                    "type": "backup",
                    "title": "Backing up to USB disk",
                    "message": f"{disk['name']}: {', '.join(ids)}",
                    "level": "info",
                }
            )
            disk = {**disk, "backups": []}  # started; only the photo import is left to offer
        if cfg["offer"]:
            _offer(disk, z_state, notify)
    return new


def dismiss(z_state: Any = None) -> None:
    if z_state is None:
        from backend.state import Z_STATE as z_state
    z_state.pending_usb = None
    z_state.ui_wake.set()
