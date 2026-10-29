"""Compression per share, read from the filesystem itself (FEAT-15).

ZFS sets compression per dataset (`zfs get/set compression`) and reports the real ratio;
btrfs takes it from the mount option (`compress=zstd:3`) or per folder
(`btrfs property … compression`, which applies to files written after the change). Other
filesystems have none. Pool rows read the same sources instead of assuming zstd.

Nothing here wakes a drive: mount options come from /proc/self/mounts and ZFS properties
from the kernel; the one call that reads the disk (a btrfs folder's property) is skipped
when the caller says the disk sleeps.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from typing import Any

from backend.proc import run_bounded

MOUNTS = "/proc/self/mounts"
_realpath = os.path.realpath

# What a person can pick, per filesystem; the first is "off"
CHOICES: dict[str, tuple[str, ...]] = {
    "zfs": ("off", "lz4", "zstd", "zstd-fast", "gzip"),
    "btrfs": ("off", "zstd", "lzo", "zlib"),
}


class CompressionError(ValueError):
    """A request that can't be done; the message says why."""


def _unescape(field: str) -> str:
    # /proc/mounts writes spaces, tabs and backslashes in octal
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def read_mounts(path: str = MOUNTS) -> list[dict[str, str]]:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 4:
            out.append(
                {
                    "device": _unescape(parts[0]),
                    "mountpoint": _unescape(parts[1]),
                    "fstype": parts[2],
                    "options": parts[3],
                }
            )
    return out


def mount_for(path: str, mounts: list[dict[str, str]] | None = None) -> dict[str, str] | None:
    """The mount a path lives on (the longest mount point that contains it)."""
    real = _realpath(path)
    best = None
    for m in mounts if mounts is not None else read_mounts():
        mp = m["mountpoint"].rstrip("/") or "/"
        if real == mp or real.startswith(mp + "/") or mp == "/":
            if best is None or len(mp) > len(best["mountpoint"].rstrip("/") or "/"):
                best = m
    return best


def btrfs_mount_option(options: str) -> str:
    """'zstd:3' style value from btrfs mount options, or 'off'."""
    for opt in options.split(","):
        key, _, value = opt.partition("=")
        if key in ("compress", "compress-force") and value:
            return "off" if value in ("no", "none") else value
    return "off"


def _call(run: Callable, cmd: list[str], timeout: float) -> subprocess.CompletedProcess:
    """Run a tool; a missing tool counts as a failed call, not an error."""
    try:
        return run(cmd, timeout=timeout, capture_output=True, text=True)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 127, "", str(e))


def _zfs_get(dataset: str, props: str, run: Callable = run_bounded) -> dict[str, str]:
    res = _call(run, ["zfs", "get", "-H", "-p", "-o", "property,value", props, dataset], 10)
    if res.returncode != 0:
        return {}
    out = {}
    for line in (res.stdout or "").splitlines():
        key, _, value = line.partition("\t")
        out[key.strip()] = value.strip()
    return out


def _ratio(value: str | None) -> float | None:
    try:
        return round(float(str(value).rstrip("x")), 2)
    except (TypeError, ValueError):
        return None


_POOL_CACHE: dict[tuple, tuple[float, str | None]] = {}
POOL_CACHE_SECONDS = 600  # pool lists are read often; the setting rarely changes (idle budget, B15)


def pool_compression(
    fs_type: str, mountpoint: str | None, dataset: str | None = None, run: Callable = run_bounded
) -> str | None:
    """The compression a pool really uses, for the pool rows; None when it can't be read here."""
    key = (fs_type, mountpoint, dataset)
    hit = _POOL_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < POOL_CACHE_SECONDS and run is run_bounded:
        return hit[1]
    value = _pool_compression(fs_type, mountpoint, dataset, run)
    _POOL_CACHE[key] = (time.monotonic(), value)
    return value


def md_compression(fs_hint: str, mountpoint: str | None) -> str | None:
    """An md (mdadm) pool row: btrfs on top reads its mount option; anything else has none."""
    return pool_compression("btrfs" if "btrfs" in fs_hint else "", mountpoint)


def _pool_compression(
    fs_type: str, mountpoint: str | None, dataset: str | None = None, run: Callable = run_bounded
) -> str | None:
    if fs_type == "zfs" and dataset:
        return _zfs_get(dataset, "compression", run).get("compression") or None
    if fs_type == "btrfs" and mountpoint:
        m = mount_for(mountpoint)
        if (
            m
            and m["fstype"] == "btrfs"
            and (m["mountpoint"].rstrip("/") or "/") == (_realpath(mountpoint).rstrip("/") or "/")
        ):
            return btrfs_mount_option(m["options"])
        return None
    if fs_type in ("xfs", "ext4", "ext3", "vfat", "exfat", "ntfs"):
        return "off"  # these have no compression
    return None


def read(path: str, *, asleep: Callable[[str], bool] = lambda _p: False, run: Callable = run_bounded) -> dict[str, Any]:
    """What a share at `path` uses now, and what can be chosen for it."""
    m = mount_for(path)
    fs = m["fstype"] if m else ""
    info: dict[str, Any] = {
        "filesystem": fs,
        "supported": fs in CHOICES,
        "choices": list(CHOICES.get(fs, ())),
        "value": "off",
        "ratio": None,
    }
    if not m or fs not in CHOICES:
        info["reason"] = f"{fs or 'This filesystem'} has no compression" if fs else "The share's folder was not found"
        return info
    if fs == "zfs":
        dataset = m["device"]
        props = _zfs_get(dataset, "compression,compressratio", run)
        if not props:
            info.update(supported=False, reason="The ZFS tools can't read this dataset here")
            return info
        own = _realpath(path) == (m["mountpoint"].rstrip("/") or "/")
        info.update(
            value=props.get("compression") or "off",
            ratio=_ratio(props.get("compressratio")),
            dataset=dataset,
            own_dataset=own,
        )
        if not own:
            info["note"] = f"Set for the whole dataset {dataset}; this share is a folder in it"
        return info
    # btrfs: the folder's own setting, else the mount option
    mount_value = btrfs_mount_option(m["options"])
    info.update(value=mount_value, from_mount=True)
    if asleep(path):
        info["asleep"] = True
        return info
    res = _call(run, ["btrfs", "property", "get", path, "compression"], 10)
    if res.returncode == 0:
        _, _, own = (res.stdout or "").strip().partition("=")
        if own:
            info.update(value="off" if own in ("no", "none") else own, from_mount=False)
    return info


def set_value(
    path: str, value: str, *, asleep: Callable[[str], bool] = lambda _p: False, run: Callable = run_bounded
) -> dict[str, Any]:
    """Change a share's compression. Applies to data written from now on."""
    current = read(path, asleep=asleep, run=run)
    fs = current["filesystem"]
    if not current["supported"]:
        raise CompressionError(current.get("reason") or "Compression can't be set here")
    if value not in CHOICES[fs]:
        raise CompressionError(f"Choose one of: {', '.join(CHOICES[fs])}")
    if fs == "zfs":
        if not current.get("own_dataset"):
            raise CompressionError(
                f"This share is a folder in the ZFS dataset {current.get('dataset')}; compression is set per dataset, "
                "so it would change every share in it. Make the share its own dataset first."
            )
        cmd = ["zfs", "set", f"compression={value}", current["dataset"]]
    else:
        if current.get("asleep"):
            raise CompressionError("The disk with this share is asleep; wake it first")
        cmd = ["btrfs", "property", "set", path, "compression", "none" if value == "off" else value]
    res = _call(run, cmd, 15)
    if res.returncode != 0:
        raise CompressionError((res.stderr or res.stdout or "The change was refused").strip()[:300])
    _POOL_CACHE.clear()
    return read(path, asleep=asleep, run=run)
