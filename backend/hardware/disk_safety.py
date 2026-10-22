"""
Checks before a disk is formatted into a pool (SEC-08).

`zpool create -f` and `mkfs -f` destroy whatever is on a disk. Before that, a
disk must be a whole block device that is not mounted (by the host or this
container), not used as swap, not part of an md/LVM/dm device or an imported ZFS\npool, and, unless the
user explicitly agreed to erase it, carries no partition table or filesystem.
"""

import os
import stat
import subprocess

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, logger


def _is_block(path: str) -> bool:
    try:
        return stat.S_ISBLK(os.stat(path).st_mode)
    except OSError:
        return False


def _kernel_name(path: str) -> str:
    return os.path.basename(os.path.realpath(path))


def _sys_block(name: str) -> str:
    for base in (HOST_SYS, "/sys"):
        p = os.path.join(base, "block", name)
        if os.path.isdir(p):
            return p
    return ""


def _partitions(name: str) -> list[str]:
    sb = _sys_block(name)
    if not sb:
        return []
    try:
        return sorted(e for e in os.listdir(sb) if e.startswith(name) and os.path.isdir(os.path.join(sb, e)))
    except OSError:
        return []


def _holders(name: str) -> list[str]:
    found: list[str] = []
    sb = _sys_block(name)
    if not sb:
        return found
    for sub in [""] + _partitions(name):
        h = os.path.join(sb, sub, "holders") if sub else os.path.join(sb, "holders")
        try:
            found += os.listdir(h)
        except OSError:
            pass
    return found


def _mounted_sources() -> dict[str, str]:
    """kernel device name -> mount point, from the host's and this container's mount tables."""
    out: dict[str, str] = {}
    for table in (os.path.join(HOST_PROC, "1", "mounts"), "/proc/self/mounts"):
        try:
            with open(table, encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2 and parts[0].startswith("/dev/"):
                        out.setdefault(os.path.basename(os.path.realpath(parts[0])), parts[1])
                        out.setdefault(os.path.basename(parts[0]), parts[1])
        except OSError:
            continue
    for table in (os.path.join(HOST_PROC, "swaps"), "/proc/swaps"):
        try:
            with open(table, encoding="utf-8", errors="replace") as f:
                for line in f.readlines()[1:]:
                    dev = line.split()[0] if line.split() else ""
                    if dev.startswith("/dev/"):
                        out.setdefault(os.path.basename(os.path.realpath(dev)), "[swap]")
        except OSError:
            continue
    return out


def _signature(path: str) -> str | None:
    """Filesystem / partition-table type found on the device, '' when blank, None when it can't be read."""
    try:
        res = subprocess.run(["blkid", "-p", "-o", "export", path], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning(f"[DiskSafety] blkid could not check {path}: {e}")
        return None
    for line in res.stdout.splitlines():
        if line.startswith(("TYPE=", "PTTYPE=")):
            return line.split("=", 1)[1]
    if res.returncode not in (0, 2):  # 2 = nothing found; anything else is an error
        logger.warning(f"[DiskSafety] blkid exited {res.returncode} on {path}: {res.stderr.strip()[:200]}")
        return None
    return ""


def _zfs_members() -> dict[str, str]:
    """kernel device name -> pool, for every device of every imported ZFS pool."""
    try:
        res = subprocess.run(["zpool", "list", "-v", "-H", "-P"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return {}  # no ZFS tools: no pools can be imported
    out: dict[str, str] = {}
    pool = ""
    for line in res.stdout.splitlines():
        fields = line.split("\t")
        if fields and fields[0] and not line.startswith(("\t", " ")):
            pool = fields[0]
            continue
        dev = next((f.strip() for f in fields if f.strip().startswith("/dev/")), "")
        if dev:
            out[os.path.basename(os.path.realpath(dev))] = pool
            out[os.path.basename(dev)] = pool
    return out


def check_disks(disks: list[str], allow_erase: bool = False) -> list[dict[str, str]]:
    """Returns one problem per disk that must not be formatted (empty list = all clear)."""
    problems: list[dict[str, str]] = []
    mounts = _mounted_sources()
    zfs = _zfs_members()
    for disk in disks:
        real = os.path.realpath(disk)
        if not (real.startswith("/dev/") or real.startswith(os.path.realpath(HOST_DEV) + "/")) or not _is_block(real):
            problems.append({"disk": disk, "reason": "not a block device"})
            continue
        name = _kernel_name(real)
        if _sys_block(name) == "":
            problems.append({"disk": disk, "reason": "not a whole disk (partition or unknown device)"})
            continue
        used = [n for n in [name] + _partitions(name) if n in mounts]
        if used:
            problems.append({"disk": disk, "reason": f"in use: {used[0]} is mounted at {mounts[used[0]]}"})
            continue
        holders = _holders(name)
        if holders:
            problems.append({"disk": disk, "reason": f"part of {', '.join(sorted(set(holders)))} (RAID/LVM/dm)"})
            continue
        in_pool = next((zfs[n] for n in [name] + _partitions(name) if n in zfs), "")
        if in_pool:  # imported pools are not in the mount table and have no holders
            problems.append({"disk": disk, "reason": f"in use by the ZFS pool {in_pool}"})
            continue
        if not allow_erase:
            sig = _signature(real)
            parts = _partitions(name)
            if sig is None:
                problems.append({"disk": disk, "reason": "could not check that it is empty", "erasable": "true"})
            elif sig or parts:
                what = sig or f"{len(parts)} partition(s)"
                problems.append({"disk": disk, "reason": f"contains data ({what})", "erasable": "true"})
    return problems
