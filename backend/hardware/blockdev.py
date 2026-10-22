"""
Which physical disks hold a path, on any Linux storage stack (AI-08).

Used by the standby guard so indexing doesn't wake sleeping disks on ZFS, Btrfs,
mdadm, LVM/LUKS or plain partitions, not only on Unraid. Everything is read from
/proc/self/mountinfo, /sys and `zpool status`, none of which touch the disks.

disks_for_path() returns:
- a list of disk names (e.g. ["sdb", "sdc"]): the spinning disks the path lives on;
- []: no local spinning disk (network or FUSE mount, tmpfs, SSD-only);
- None: a local filesystem whose disks couldn't be determined. Callers treat
  this as "might be asleep" (fail closed).
"""

import os
import re
import subprocess
import time
from typing import Optional

from backend import config

NETWORK_FS = {
    "nfs",
    "nfs4",
    "cifs",
    "smb3",
    "smbfs",
    "sshfs",
    "fuse.sshfs",
    "fuse.rclone",
    "9p",
    "ceph",
    "glusterfs",
    "fuse.glusterfs",
    "davfs",
    "fuse.s3fs",
    "fuse.gcsfuse",
    "afs",
}
NO_DISK_FS = {
    "rootfs",
    "tmpfs",
    "ramfs",
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "overlay",
    "squashfs",
}
_ZPOOL_CACHE: dict[str, tuple[float, list[str]]] = {}


def _sys_root() -> str:
    host = getattr(config, "HOST_SYS", "") or ""
    return host if host and os.path.isdir(os.path.join(host, "block")) else "/sys"


def _unescape(field: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), field)


def read_mounts(mountinfo: str = "/proc/self/mountinfo") -> list[dict]:
    mounts = []
    try:
        with open(mountinfo, encoding="utf-8", errors="replace") as f:
            for line in f:
                left, _, right = line.partition(" - ")
                lf, rf = left.split(), right.split()
                if len(lf) < 5 or len(rf) < 2:
                    continue
                mounts.append(
                    {
                        "mountpoint": _unescape(lf[4]),
                        "majmin": lf[2],
                        "root": _unescape(lf[3]),
                        "fstype": rf[0],
                        "source": _unescape(rf[1]),
                    }
                )
    except OSError:
        pass
    return mounts


def mount_for(path: str, mounts: list[dict] | None = None) -> dict | None:
    """The mount a path lives on (longest matching mount point)."""
    path = os.path.realpath(path) if os.path.exists(path) else os.path.normpath(path)
    best = None
    for m in mounts if mounts is not None else read_mounts():
        mp = m["mountpoint"].rstrip("/") or "/"
        if path == mp or path.startswith(mp + "/") or mp == "/":
            if best is None or len(mp) >= len(best["mountpoint"].rstrip("/") or "/"):
                best = m
    return best


def _name_for_majmin(majmin: str, sysroot: str) -> str | None:
    link = os.path.join(sysroot, "dev", "block", majmin)
    try:
        return os.path.basename(os.path.realpath(link)) if os.path.exists(link) else None
    except OSError:
        return None


def _block_dir(name: str, sysroot: str) -> str | None:
    p = os.path.join(sysroot, "class", "block", name)
    return os.path.realpath(p) if os.path.exists(p) else None


def physical_disks(name: str, sysroot: str | None = None, _seen: set | None = None) -> list[str]:
    """Expands a block device (partition, md, dm, …) to the whole disks under it."""
    sysroot = sysroot or _sys_root()
    _seen = _seen if _seen is not None else set()
    if not name or name in _seen:
        return []
    _seen.add(name)
    d = _block_dir(name, sysroot)
    if not d:
        return []
    slaves = os.path.join(d, "slaves")
    if os.path.isdir(slaves) and os.listdir(slaves):
        out: list[str] = []
        for s in sorted(os.listdir(slaves)):
            out += [x for x in physical_disks(s, sysroot, _seen) if x not in out]
        return out
    if os.path.exists(os.path.join(d, "partition")):
        return [os.path.basename(os.path.dirname(d))]
    return [name]


def is_rotational(disk: str, sysroot: str | None = None) -> bool:
    sysroot = sysroot or _sys_root()
    try:
        with open(os.path.join(sysroot, "block", disk, "queue", "rotational")) as f:
            return f.read().strip() != "0"
    except OSError:
        return True  # unknown: assume it can sleep


def zfs_pool_disks(pool: str, sysroot: str | None = None, runner=subprocess.run) -> list[str] | None:
    now = time.time()
    hit = _ZPOOL_CACHE.get(pool)
    if hit and now - hit[0] < 60:
        return hit[1]
    try:
        r = runner(["zpool", "status", "-P", "-L", pool], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    devs: list[str] = []
    for m in re.finditer(r"\s(/dev/\S+)", r.stdout or ""):
        base = os.path.basename(m.group(1))
        for disk in physical_disks(base, sysroot) or [re.sub(r"(p?\d+)$", "", base)]:
            if disk not in devs:
                devs.append(disk)
    _ZPOOL_CACHE[pool] = (now, devs)
    return devs


def btrfs_disks(source: str, sysroot: str | None = None) -> list[str] | None:
    sysroot = sysroot or _sys_root()
    part = os.path.basename(source)
    base = os.path.join(sysroot, "fs", "btrfs")
    try:
        for uuid in os.listdir(base):
            devdir = os.path.join(base, uuid, "devices")
            if os.path.isdir(devdir) and part in os.listdir(devdir):
                out: list[str] = []
                for d in sorted(os.listdir(devdir)):
                    out += [x for x in physical_disks(d, sysroot) if x not in out]
                return out
    except OSError:
        pass
    disks = physical_disks(part, sysroot)
    return disks or None


def disks_for_path(
    path: str, mounts: list[dict] | None = None, sysroot: str | None = None, runner=subprocess.run
) -> list[str] | None:
    sysroot = sysroot or _sys_root()
    m = mount_for(path, mounts)
    if not m:
        return None
    fstype = m["fstype"]
    if fstype in NETWORK_FS or fstype in NO_DISK_FS or (fstype.startswith("fuse.") and fstype != "fuse.shfs"):
        return []
    if fstype == "fuse.shfs":
        return None  # an Unraid user share mounted somewhere unexpected
    if fstype == "zfs":
        disks = zfs_pool_disks(m["source"].split("/")[0], sysroot, runner)
    elif fstype == "btrfs":
        disks = btrfs_disks(m["source"], sysroot)
    else:
        name = _name_for_majmin(m["majmin"], sysroot)
        if not name and m["source"].startswith("/dev/"):
            name = os.path.basename(os.path.realpath(m["source"]))
        disks = physical_disks(name, sysroot) if name and _block_dir(name, sysroot) else None
    if disks is None:
        return None
    return [d for d in disks if is_rotational(d, sysroot)]
