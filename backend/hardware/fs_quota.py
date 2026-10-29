"""Quotas the filesystem itself enforces (FEAT-10, REL-19).

A limit ZettNAS only checks on its own uploads doesn't stop SMB, NFS or WebDAV. Where the
filesystem can hold it, the limit is set there:

    btrfs   a subvolume's quota group (btrfs qgroup limit)
    ZFS     a dataset's refquota
    XFS     a project quota on the folder (xfs_quota), when the volume is mounted with prjquota

Anything else (ext4 without project quotas, Unraid's /mnt/user, network mounts) stays advisory:
ZettNAS checks its own uploads and says so. Each answer says which it is and why.
"""

from __future__ import annotations

import os
import subprocess
import zlib
from collections.abc import Callable
from typing import Any

from backend.hardware.share_compression import mount_for
from backend.proc import run_bounded


def _call(run: Callable, cmd: list[str], timeout: float = 20) -> subprocess.CompletedProcess:
    try:
        return run(cmd, timeout=timeout, capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _result(enforced: bool, method: str | None, reason: str = "") -> dict[str, Any]:
    return {"enforced": enforced, "method": method, "reason": reason}


def project_id(path: str) -> int:
    """A stable XFS project id for a folder (10000-999999)."""
    return 10000 + zlib.crc32(os.path.realpath(path).encode()) % 990000


def _btrfs(path: str, limit: int, run: Callable) -> dict[str, Any]:
    if _call(run, ["btrfs", "subvolume", "show", path]).returncode != 0:
        return _result(False, None, "This folder is not a btrfs subvolume, so btrfs can't limit it on its own.")
    _call(run, ["btrfs", "quota", "enable", path])
    res = _call(run, ["btrfs", "qgroup", "limit", str(limit) if limit else "none", path])
    if res.returncode != 0:
        return _result(False, None, f"btrfs refused the limit: {(res.stderr or '').strip()[:200]}")
    return _result(True, "btrfs-qgroup")


def _zfs(path: str, dataset: str, own: bool, limit: int, run: Callable) -> dict[str, Any]:
    if not own:
        return _result(False, None, f"This folder is inside the ZFS dataset {dataset}; ZFS limits whole datasets.")
    res = _call(run, ["zfs", "set", f"refquota={limit if limit else 'none'}", dataset])
    if res.returncode != 0:
        return _result(False, None, f"ZFS refused the limit: {(res.stderr or '').strip()[:200]}")
    return _result(True, "zfs-refquota")


def _xfs(path: str, mountpoint: str, options: str, limit: int, run: Callable) -> dict[str, Any]:
    if not any(o in options.split(",") for o in ("prjquota", "pquota", "pqnoenforce")):
        return _result(False, None, "This XFS volume is mounted without project quotas (prjquota).")
    pid = project_id(path)
    steps = [
        ["xfs_quota", "-x", "-c", f"project -s -p {path} {pid}", mountpoint],
        ["xfs_quota", "-x", "-c", f"limit -p bhard={limit if limit else 0} {pid}", mountpoint],
    ]
    for cmd in steps:
        res = _call(run, cmd)
        if res.returncode != 0:
            return _result(
                False, None, f"xfs_quota refused the limit: {(res.stderr or res.stdout or '').strip()[:200]}"
            )
    return _result(True, "xfs-project")


def apply(
    path: str, limit_bytes: int, run: Callable = run_bounded, mounts: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    """Sets (or with 0 clears) the filesystem's own limit on a folder. Never raises."""
    if not os.path.isdir(path):
        return _result(False, None, "The folder doesn't exist.")
    m = mount_for(path, mounts)
    fs = m["fstype"] if m else ""
    limit = max(0, int(limit_bytes or 0))
    if fs == "btrfs":
        return _btrfs(path, limit, run)
    if fs == "zfs" and m:
        own = os.path.realpath(path).rstrip("/") == (m["mountpoint"].rstrip("/") or "/")
        return _zfs(path, m["device"], own, limit, run)
    if fs == "xfs" and m:
        return _xfs(path, m["mountpoint"], m["options"], limit, run)
    label = {
        "fuse.shfs": "Unraid's user shares",
        "ext4": "ext4 here",
        "nfs": "a network mount",
        "nfs4": "a network mount",
        "cifs": "a network mount",
    }
    where = label.get(fs, fs or "this filesystem")
    return _result(False, None, f"{where} can't enforce a folder limit; ZettNAS checks its own uploads.")


def zfs_child_dataset(
    parent: str, name: str, run: Callable = run_bounded, mounts: list[dict[str, str]] | None = None
) -> str | None:
    """Creates <dataset of parent>/<name> when parent is itself a ZFS dataset's mount point, so a
    person's home can carry its own refquota. Returns the new folder, or None when not ZFS."""
    m = mount_for(parent, mounts)
    if not m or m["fstype"] != "zfs":
        return None
    if os.path.realpath(parent).rstrip("/") != (m["mountpoint"].rstrip("/") or "/"):
        return None
    if _call(run, ["zfs", "create", f"{m['device']}/{name}"]).returncode != 0:
        return None
    return os.path.join(parent, name)
