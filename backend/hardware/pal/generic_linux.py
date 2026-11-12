"""Generic Linux: Btrfs, ZFS and mdadm pools, Samba and NFS shares managed here.

Part of the storage abstraction layer (backend/hardware/pal); split out of pal_storage.py (ARC-5)."""

import contextlib
import json
import os
import re
import shutil
import sqlite3
import struct
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from enum import Enum, StrEnum
from typing import Any, Optional

from pydantic import BaseModel, Field

from backend.config import HOST_DEV, HOST_PROC, HOST_SYS, POOL_PATH, logger
from backend.fsutil import atomic_write_json, child_path
from backend.hardware import fs_quota
from backend.hardware.pal import base as pal_base
from backend.hardware.pal.base import (
    NetworkShare,
    PlatformCapabilities,
    PlatformCapabilityError,
    PlatformType,
    PoolMember,
    StoragePlatformAdapter,
    StoragePool,
    _whole_disk,
)
from backend.hardware.share_compression import md_compression, pool_compression
from backend.hardware.unraid import _find_emhttp_dir, read_unraid_status
from backend.ignored_errors import ignored
from backend.settings import test_mode


def fs_of(path: str, mounts: str = "/proc/mounts") -> str:
    """The filesystem type of the mount that holds path ("" when it can't be told), by the longest
    mount point in /proc/mounts that contains it."""
    path = os.path.realpath(path)
    best, fs = "", ""
    try:
        with open(mounts, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mnt = parts[1].replace("\\040", " ")
                inside = path == mnt or path.startswith(mnt.rstrip("/") + "/")
                if inside and len(mnt) >= len(best):
                    best, fs = mnt, parts[2]
    except OSError:
        return ""
    return fs


def is_subvolume(path: str) -> bool:
    """Whether path is the top folder of a btrfs subvolume (its inode number is always 256)."""
    try:
        return os.stat(path).st_ino == 256 and fs_of(path) == "btrfs"
    except OSError:
        return False


def _mount_rows(mounts: str = "/proc/mounts") -> list[tuple[str, str, str]]:
    try:
        with open(mounts, encoding="utf-8") as f:
            rows = [line.split() for line in f]
    except OSError:
        return []
    return [(r[0].replace("\\040", " "), r[1].replace("\\040", " "), r[2]) for r in rows if len(r) >= 3]


def is_mount_point(path: str, mounts: str = "/proc/mounts") -> bool:
    """Whether something is mounted at path. os.path.ismount() also says yes for every btrfs
    subvolume (it has a device number of its own), which kept the swap rollback from ever running."""
    real = os.path.realpath(path)
    return any(mnt == real for _dev, mnt, _fs in _mount_rows(mounts))


# Where ZFS snapshots are mounted to be read when .zfs/snapshot can't show them (in a container)
SNAPSHOT_VIEWS = os.path.join(tempfile.gettempdir(), "zettnas-snapshot-views")


def zfs_mounts(mounts: str = "/proc/mounts") -> dict[str, str]:
    """Mounted ZFS datasets: dataset name -> mount point."""
    return {dev: mnt for dev, mnt, fs in _mount_rows(mounts) if fs == "zfs"}


def zfs_dataset_at(path: str, mounts: str = "/proc/mounts") -> str:
    """The ZFS dataset mounted exactly at path ("" when there is none)."""
    path = os.path.realpath(path)
    return next((ds for ds, mnt in zfs_mounts(mounts).items() if mnt == path), "")


def own_usage(path: str, run) -> tuple[int, int] | None:
    """A shared folder's own (used, limit) where the filesystem already keeps it: a ZFS dataset's
    "used" and quota, or a btrfs subvolume's qgroup when quotas are on. Read from metadata, never
    by walking the files, which would wake sleeping drives (B35, confirmed 11 Nov 2026). None when
    the folder has no figure of its own; limit 0 means no quota."""
    from backend.hardware.pal.base import storage_tools

    tools = storage_tools()
    if tools.get("zfs"):
        ds = zfs_dataset_at(path)
        if ds:
            code, out, _ = run(["zfs", "get", "-Hp", "-o", "value", "used,quota", ds])
            vals = out.split() if code == 0 else []
            if len(vals) == 2 and vals[0].isdigit():
                return int(vals[0]), int(vals[1]) if vals[1].isdigit() else 0
    if tools.get("btrfs") and is_subvolume(path):
        # qgroupid rfer excl max_rfer [path]; it fails when quotas are off
        code, out, _ = run(["btrfs", "qgroup", "show", "-f", "-r", "--raw", path])
        for line in out.splitlines() if code == 0 else []:
            parts = line.split()
            if len(parts) >= 3 and re.fullmatch(r"0/\d+", parts[0]) and parts[1].isdigit():
                return int(parts[1]), int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    return None


ZFS_NAME_PROP = "org.zettnas:name"  # the snapshot's own name: ZFS names can't hold its "@"
ZFS_HOLD_TAG = "zettnas-worm"  # a hold stops zfs destroy, even by root, until released


def zfs_snapshot_part(name: str) -> str:
    """A snapshot name ZFS accepts after the "@": letters, digits and _ . : - only."""
    return re.sub(r"[^A-Za-z0-9_.:-]", "-", name)[:200] or "snapshot"


def _tree_bytes(path: str) -> int:
    """The bytes of the files under path, links not followed."""
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                continue
    return total


class GenericLinuxStorageAdapter(StoragePlatformAdapter):
    """
    Generic Linux Storage Platform Adapter.
    Operates in Active Provisioner Mode (or Observer Mode when unprivileged).
    Supports Btrfs multi-device pools, ext4/xfs volumes, subvolume snapshots,
    and managed Samba/WebDAV shares.
    """

    def __init__(self, pool_path: str | None = None):
        self._pool_path = pool_path or pal_base.POOL_PATH or "/mnt/storage"

    def _nested_subvolumes(self, path: str) -> bool:
        """Whether a subvolume holds subvolumes of its own (True when it can't be told)."""
        code, out, _ = self._run_cmd(["btrfs", "subvolume", "list", "-o", path])
        return code != 0 or bool(out.strip())

    def can_swap_in(self, live_root: str, snap_path: str) -> bool:
        """Whether a share can be rolled back by swapping its snapshot in (NREL-7): both are btrfs
        subvolumes, the share isn't mounted on its own and holds no subvolume of its own (a
        snapshot doesn't take those along)."""
        return (
            is_subvolume(live_root)
            and is_subvolume(snap_path)
            and not is_mount_point(live_root)
            and not self._nested_subvolumes(live_root)
        )

    def _carry_over(self, src: str, dest: str) -> None:
        """dest becomes a copy of src that shares its blocks (reflink): no room, little time."""
        if os.path.lexists(dest):
            if os.path.isdir(dest) and not os.path.islink(dest):
                shutil.rmtree(dest)
            else:
                os.unlink(dest)
        if not os.path.lexists(src):
            return
        code, _, err = self._run_cmd(["cp", "-a", "--reflink=always", src, dest])
        if code:
            raise RuntimeError(f"{os.path.basename(src)} could not be carried over ({err}); nothing was changed.")

    def swap_in_snapshot(self, live_root: str, snap_path: str, keep: tuple[str, ...]) -> None:
        """Rolls a share back by putting a writable clone of the snapshot in its place: seconds,
        no data copied, no room needed. The entries named in keep stay as they are now. Raises
        when it can't, with the share left as it was."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        new, old = f"{live_root}.rollback-{stamp}", f"{live_root}.before-rollback-{stamp}"
        code, _, err = self._run_cmd(["btrfs", "subvolume", "snapshot", snap_path, new])
        if code:
            raise RuntimeError(f"The snapshot could not be cloned ({err}); nothing was changed.")
        try:
            for name in keep:
                self._carry_over(os.path.join(live_root, name), os.path.join(new, name))
            os.rename(live_root, old)
            try:
                os.rename(new, live_root)
            except OSError:
                os.rename(old, live_root)
                raise
        except (OSError, RuntimeError):
            self._run_cmd(["btrfs", "subvolume", "delete", new])
            raise
        code, _, err = self._run_cmd(["btrfs", "subvolume", "delete", old])
        if code:  # the share is rolled back; only the old copy is left over
            logger.warning("[PAL] %s could not be removed: %s", old, err)

    def can_convert(self, path: str) -> bool:
        """Whether a share that is a plain folder can become a btrfs subvolume or, on a ZFS pool, a
        dataset of its own, so its snapshots work (NREL-5)."""
        from backend.hardware.pal.base import storage_tools

        if not os.path.isdir(path) or os.path.ismount(path):
            return False
        fs = fs_of(path)
        if fs == "btrfs":
            return not is_subvolume(path) and storage_tools()["btrfs"]
        if fs == "zfs":
            parent = os.path.dirname(path.rstrip("/")) or "/"
            return storage_tools()["zfs"] and not zfs_dataset_at(path) and bool(zfs_dataset_at(parent))
        return False

    def convert_to_subvolume(self, path: str) -> str:
        """Makes a folder share a subvolume with the same name and files: a new subvolume gets a
        copy that shares their blocks, then the two swap names. Returns the old folder, for the
        caller to remove; on failure the share is left as it was. On ZFS it becomes a dataset."""
        if fs_of(path) == "zfs":
            return self._convert_to_dataset(path)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        new, old = f"{path}.subvolume-{stamp}", f"{path}.before-subvolume-{stamp}"
        code, _, err = self._run_cmd(["btrfs", "subvolume", "create", new])
        if code:
            raise RuntimeError(f"The subvolume could not be made ({err}); nothing was changed.")
        code, _, err = self._run_cmd(["cp", "-a", "--reflink=always", os.path.join(path, "."), new])
        if code:
            self._run_cmd(["btrfs", "subvolume", "delete", new])
            raise RuntimeError(f"The files could not be copied over ({err}); nothing was changed.")
        os.rename(path, old)
        try:
            os.rename(new, path)
        except OSError:
            os.rename(old, path)
            self._run_cmd(["btrfs", "subvolume", "delete", new])
            raise
        return old

    def _convert_to_dataset(self, path: str) -> str:
        """A folder share on a ZFS pool becomes a dataset with the same name and files: a dataset
        beside it gets a copy (ZFS can't share blocks across datasets, so there must be room), the
        folder steps aside and the dataset is renamed into its place. Returns the old folder."""
        parent = os.path.dirname(path.rstrip("/")) or "/"
        name = os.path.basename(path.rstrip("/"))
        parent_ds = zfs_dataset_at(parent)
        if not parent_ds:
            raise RuntimeError("The folder above this share isn't a ZFS dataset; nothing was changed.")
        need = _tree_bytes(path)
        free = shutil.disk_usage(parent).free
        if need > free:
            raise RuntimeError(
                f"Not enough free space: the files take {need / 1e9:.1f} GB and {free / 1e9:.1f} GB is free; nothing was changed."
            )
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tmp_ds = f"{parent_ds}/{name}.dataset-{stamp}"
        tmp_path = os.path.join(parent, f"{name}.dataset-{stamp}")
        code, _, err = self._run_cmd(["zfs", "create", tmp_ds])
        if code or not os.path.isdir(tmp_path):
            raise RuntimeError(f"The dataset could not be made ({err}); nothing was changed.")
        code, _, err = self._run_cmd(["cp", "-a", os.path.join(path, "."), tmp_path])
        if code:
            self._run_cmd(["zfs", "destroy", "-r", tmp_ds])
            raise RuntimeError(f"The files could not be copied over ({err}); nothing was changed.")
        old = os.path.join(parent, f"{name}.before-dataset-{stamp}")
        os.rename(path, old)
        code, _, err = self._run_cmd(["zfs", "rename", tmp_ds, f"{parent_ds}/{name}"])
        if code:
            os.rename(old, path)
            self._run_cmd(["zfs", "destroy", "-r", tmp_ds])
            raise RuntimeError(f"The dataset could not take the share's place ({err}); nothing was changed.")
        return old

    def _make_share_dir(self, full_path: str) -> str:
        """The share's folder (NREL-5). On btrfs it is a subvolume and on ZFS a dataset, so the
        default snapshots and quotas work on it; elsewhere, or if that fails, a plain folder.
        Returns which it made."""
        from backend.hardware.pal.base import storage_tools

        parent = os.path.dirname(full_path.rstrip("/")) or "/"
        fs = "" if os.path.exists(full_path) else fs_of(parent)
        if fs == "btrfs" and storage_tools()["btrfs"]:
            code, _, err = self._run_cmd(["btrfs", "subvolume", "create", full_path])
            if code == 0:
                return "subvolume"
            logger.warning("[PAL] %s: no btrfs subvolume (%s); a plain folder instead", full_path, err)
        elif fs == "zfs" and storage_tools()["zfs"] and zfs_dataset_at(parent):
            # a dataset of its own, mounted at the share's path by inheritance, so it can be snapshotted
            child = f"{zfs_dataset_at(parent)}/{os.path.basename(full_path.rstrip('/'))}"
            code, _, err = self._run_cmd(["zfs", "create", child])
            if code == 0 and os.path.isdir(full_path):
                return "dataset"
            logger.warning("[PAL] %s: no ZFS dataset (%s); a plain folder instead", full_path, err)
        try:
            os.makedirs(full_path, exist_ok=True)
        except OSError as e:
            logger.warning("[PAL] Could not pre-create share dir %s: %s", full_path, e)
        return "folder"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.GENERIC_LINUX

    def get_capabilities(self) -> PlatformCapabilities:
        from backend.hardware.pal.base import storage_tools

        tools = storage_tools()
        has_cow = tools["btrfs"] or tools["zfs"]
        # NREL-5: btrfs subvolume or ZFS dataset snapshots, so the pool must be one of those
        pool_fs = fs_of(self._pool_path)
        snapshots = (tools["btrfs"] and pool_fs == "btrfs") or (tools["zfs"] and pool_fs == "zfs")
        missing = [n for n in ("btrfs", "zfs", "mdadm") if not tools[n]]
        return PlatformCapabilities(
            platform=PlatformType.GENERIC_LINUX,
            is_observer_mode=False,
            can_create_pools=True,
            can_destroy_pools=True,
            can_manage_shares=True,
            # REL-4: offer only what the tools in this image can do
            can_trigger_scrub=has_cow or tools["mdadm"],
            can_snapshot=snapshots,
            storage_tools=tools,
            supported_filesystems=[f for f in ("btrfs", "ext4", "xfs", "zfs") if f in ("ext4", "xfs") or tools[f]],
            description="Active Provisioner Mode: Bare-metal Linux host detected. Pool and share management enabled."
            + (f" Not available here: {', '.join(missing)} tools are missing." if missing else ""),
        )

    def _run_cmd(self, cmd: list[str]) -> tuple[int, str, str]:
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
        """
        Resolves relative or bare disk names to canonical block device path,
        strictly preferring persistent /dev/disk/by-id/ identifiers to prevent
        device node shuffling from corrupting external USB/TB and SATA pools.
        """
        d = disk.strip()
        # If already specified as a by-id or by-path canonical path
        if "/disk/by-" in d:
            if os.path.exists(d):
                return d
            host_p = os.path.join(pal_base.HOST_DEV, d.lstrip("/"))
            if os.path.exists(host_p):
                return host_p
            return d

        # Determine target dev name (e.g. "sda", "nvme1n1")
        base_name = os.path.basename(d)

        # Search for canonical persistent /dev/disk/by-id/ symlink
        for by_id_dir in ["/dev/disk/by-id", os.path.join(pal_base.HOST_DEV, "disk/by-id")]:
            if os.path.isdir(by_id_dir):
                try:
                    candidates = []
                    for entry in os.listdir(by_id_dir):
                        # Skip partition links
                        if re.search(r"-part\d+$", entry):
                            continue
                        link_path = os.path.join(by_id_dir, entry)
                        try:
                            target = os.path.realpath(link_path)
                            if os.path.basename(target) == base_name:
                                candidates.append(link_path)
                        except OSError:
                            continue

                    if candidates:
                        # Rank candidates: wwn- > ata- / nvme- > usb- > scsi-
                        def _rank(p: str) -> int:
                            name = os.path.basename(p)
                            if name.startswith("wwn-"):
                                return 0
                            if name.startswith("ata-") or name.startswith("nvme-"):
                                return 1
                            if name.startswith("usb-"):
                                return 2
                            if name.startswith("scsi-"):
                                return 3
                            return 4

                        candidates.sort(key=_rank)
                        return candidates[0]
                except Exception as e:
                    logger.debug(f"[PAL] by-id resolution error for {disk}: {e}")

        # Fallback to standard block device node
        if d.startswith("/"):
            if os.path.exists(d):
                return d
            host_disk = os.path.join(pal_base.HOST_DEV, d.lstrip("/"))
            if os.path.exists(host_disk):
                return host_disk
            return d

        for base in [pal_base.HOST_DEV, "/dev"]:
            cand = os.path.join(base, d)
            if os.path.exists(cand):
                return cand
        return f"/dev/{d}"

    _busy_cache_ts: float = 0.0
    _busy_cache_val: bool = False

    def is_storage_busy(self) -> bool:
        """Checks if a scrub or balance is actively running across Btrfs or OpenZFS pools (10s TTL cache)."""
        if test_mode():
            return self._check_is_storage_busy_uncached()
        now = time.time()
        if now - getattr(self, "_busy_cache_ts", 0.0) < 10.0:
            return getattr(self, "_busy_cache_val", False)

        val = self._check_is_storage_busy_uncached()
        self._busy_cache_ts = now
        self._busy_cache_val = val
        return val

    def _check_is_storage_busy_uncached(self) -> bool:
        # Check Btrfs scrub (e.g. "scrub status for ...: running" vs "no scrub running")
        code, out, _ = self._run_cmd(["btrfs", "scrub", "status", self._pool_path])
        out_l = out.lower()
        if code == 0 and ("running" in out_l and "no scrub" not in out_l and "not running" not in out_l):
            return True
        # Check Btrfs balance (e.g. "Balance on ... is running" vs "No balance found on ...")
        code, out, _ = self._run_cmd(["btrfs", "balance", "status", self._pool_path])
        out_l = out.lower()
        if code == 0 and ("is running" in out_l or "balance running" in out_l):
            return True
        # Check OpenZFS scrub/resilver
        code, out, _ = self._run_cmd(["zpool", "status"])
        out_l = out.lower()
        return bool(code == 0 and ("scrub in progress" in out_l or "resilver in progress" in out_l))

    def resolve_pool(self, pool_id: str) -> StoragePool:
        """The pool an id names, with its kind and its real folder (SET-06, engine rule 1). Scrub,
        eject, rename, remove and the monthly check all ask here. Each of them used to work the
        path out for itself, as "<pool folder>/<id>"; ids are device names, so for a btrfs,
        ext4, XFS or md pool that folder does not exist, and every scrub ran on the main pool.
        An id may carry "zfs:" in front (older callers); "default" is the main pool."""
        wanted = str(pool_id or "").strip()
        if wanted.startswith(("zfs:", "zpool:")):
            wanted = wanted.split(":", 1)[1]
        if wanted in ("", "default"):
            wanted = "default_pool"
        pools = self.list_pools()
        found = next((p for p in pools if p.id == wanted), None) or next((p for p in pools if p.name == wanted), None)
        if found is None and wanted == "default_pool":
            # the main pool is always there, also where the list shows it under another id
            at_main = next((p for p in pools if p.mountpoint == self._pool_path), None)
            found = at_main or StoragePool(
                id="default_pool",
                name="Primary Storage Pool",
                pool_type="single",
                fs_type=self._fs_type_at(self._pool_path),
                mountpoint=self._pool_path,
            )
        if found is None:
            raise LookupError(f"There is no pool “{pool_id}” on this system.")
        return found

    def _fs_type_at(self, path: str) -> str:
        """The file system a folder is on, from the mount table; "unknown" when it does not say."""
        best, fs_type = "", "unknown"
        for m in self._parse_mounts():
            target = str(m.get("target") or m.get("mountpoint") or "")
            if target and (path == target or path.startswith(target.rstrip("/") + "/")) and len(target) > len(best):
                best, fs_type = target, str(m.get("fstype") or m.get("fs_type") or "unknown")
        return fs_type

    def trigger_scrub(self, pool_id: str, action: str = "start") -> dict[str, Any]:
        """Starts, stops or reads the check of the pool that is named: `zpool scrub` for ZFS,
        `btrfs scrub` on the pool's own folder for btrfs. Other file systems have no check of
        their own; the answer says so and nothing is started."""
        self._busy_cache_ts = 0.0
        pool = self.resolve_pool(pool_id)
        base = {"pool_id": pool.id, "pool": pool.name, "action": action if action in ("start", "cancel") else "status"}
        if pool.fs_type == "zfs":
            cmd = {"start": ["zpool", "scrub", pool.id], "cancel": ["zpool", "scrub", "-s", pool.id]}.get(action)
            if cmd is None:
                _code, out, err = self._run_cmd(["zpool", "status", pool.id])
                state = "active" if "scrub in progress" in out.lower() else "idle"
                return {**base, "platform": "zfs", "status": state, "raw": out or err}
            return self._scrub_answer({**base, "platform": "zfs"}, pool, action, *self._run_cmd(cmd))
        if pool.fs_type != "btrfs" or not pool.mountpoint:
            return {
                **base,
                "platform": "generic_linux",
                "status": "unsupported",
                "message": f"{pool.name} is {pool.fs_type}, which has no check of its own. Nothing was started.",
            }
        target = pool.mountpoint
        if action in ("start", "cancel"):
            answer = self._run_cmd(["btrfs", "scrub", action, target])
            return self._scrub_answer({**base, "platform": "generic_linux"}, pool, action, *answer)
        _code, out, err = self._run_cmd(["btrfs", "scrub", "status", "-d", target])
        idle = "no scrub running" in out.lower() or "not running" in out.lower()
        return {**base, "platform": "generic_linux", "status": "idle" if idle else "active", "raw": out or err}

    @staticmethod
    def _scrub_answer(base: dict[str, Any], pool: StoragePool, action: str, code: int, out: str, err: str) -> dict:
        """What a start or a stop answers. The message names the pool only when it worked: it said
        "Scrub initiated on ..." also when the command had failed."""
        ok = code == 0
        done = "started" if action == "start" else "cancelled"
        said = f"The check of {pool.name} was {done}." if ok else f"The check of {pool.name} could not be {done}."
        return {**base, "status": done if ok else "error", "output": out or err, "message": said}

    def _main_pool_facts(self) -> tuple[str, str]:
        """The main pool's file system and its level, as measured: (fs_type, profile).

        It was always called btrfs, and its level was guessed as "raid1" whenever the NAS had two
        drives and btrfs gave no answer, which the page then showed as "parity protected". When
        `btrfs filesystem df` failed, `btrfs filesystem show` was run on the folder: that looks at
        every drive, and the statistics collector did it every 30 seconds (SET-09).

        btrfs is asked about the folder itself (one call that touches no drive). Where it answers,
        the pool is btrfs with the level it names. Where it does not, the file system is the one
        the mount table gives for exactly this folder, else "unknown": the folder may be mapped
        into the container from another place, so a parent's file system proves nothing."""
        code, out, _ = self._run_cmd(["btrfs", "filesystem", "df", self._pool_path])
        if code == 0 and out.strip():
            for line in out.strip().splitlines():
                match = re.search(r"^Data,\s*([A-Za-z0-9_]+):", line)
                if match:
                    return "btrfs", match.group(1).lower()
            return "btrfs", ""
        for m in self._parse_mounts():
            if str(m.get("target") or m.get("mountpoint") or "").rstrip("/") == self._pool_path.rstrip("/"):
                return str(m.get("fstype") or m.get("fs_type") or "unknown"), ""
        return "unknown", ""

    def list_pools(self) -> list[StoragePool]:
        pools: list[StoragePool] = []
        is_overlay = self._is_os_overlay_or_emmc(self._pool_path)
        hal_disks = {d.name: d for d in self._discover_hal_disks()}
        mounts = self._parse_mounts()
        claimed_mount_paths: set = set()

        # 1. Discover mdadm Linux Software RAID arrays if present
        mdstats = self._parse_mdstat()
        data_md_arrays = [m for m, i in mdstats.items() if i.get("size_bytes", 0) >= 20 * 1024 * 1024 * 1024]
        has_multiple_md = len(data_md_arrays) > 1

        for md_dev, info in sorted(mdstats.items()):
            size_b = info.get("size_bytes", 0)
            if size_b < 20 * 1024 * 1024 * 1024:
                continue

            level = info.get("level", "raid5").lower()
            degraded = info.get("degraded", False)
            status = "DEGRADED" if degraded else "HEALTHY"
            parity = level in ("raid1", "raid5", "raid6", "raid10")

            members: list[PoolMember] = []
            for m_token in info.get("members", []):
                clean_disk = _whole_disk(m_token)
                if clean_disk in hal_disks:
                    members.append(hal_disks[clean_disk])
                else:
                    members.append(
                        PoolMember(
                            name=m_token,
                            device=clean_disk,
                            id=m_token,
                            type="Data" if "nvme" not in clean_disk else "Cache",
                            role="data" if "nvme" not in clean_disk else "cache",
                            status="OK" if not degraded else "DEGRADED",
                        )
                    )

            mount_path = None
            md_devices = {md_dev, f"/dev/{md_dev}"}
            for s_base in (pal_base.HOST_SYS, "/sys", "/host/sys"):
                if not s_base:
                    continue
                holders_dir = os.path.join(s_base, "block", md_dev, "holders")
                if os.path.isdir(holders_dir):
                    try:
                        for h in os.listdir(holders_dir):
                            md_devices.add(h)
                            md_devices.add(f"/dev/{h}")
                            md_devices.add(f"/dev/mapper/{h}")
                    except Exception:
                        ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_pools")

            for m in mounts:
                dev = m.get("device", "")
                mp = m.get("mountpoint", "")
                if any(target in dev for target in md_devices):
                    mount_path = mp
                    claimed_mount_paths.add(mp)
                    break

            size_b, used_b, free_b, pct, resolved_fstype = self._get_mount_or_device_usage(
                mount_path=mount_path,
                dev_name=md_dev,
                fallback_total=size_b,
            )

            is_nvme_array = "nvme" in str(members[0].device if members else "")
            if not has_multiple_md:
                friendly_name = (
                    f"Primary Storage Array ({level.upper()})"
                    if not is_nvme_array
                    else f"NVMe Storage Array ({level.upper()})"
                )
            else:
                friendly_name = (
                    f"Storage Array {md_dev.upper()} ({level.upper()})"
                    if not is_nvme_array
                    else f"NVMe Storage Array {md_dev.upper()} ({level.upper()})"
                )

            pools.append(
                StoragePool(
                    id=md_dev,
                    name=friendly_name,
                    pool_type=f"md_{level}",
                    fs_type=resolved_fstype or ("btrfs" if mount_path and "btrfs" in str(mounts) else "ext4"),
                    fs_profile=level,
                    status=status,
                    mountpoint=mount_path or f"/{md_dev}",
                    total_bytes=size_b,
                    used_bytes=used_b,
                    free_bytes=free_b,
                    used_pct=pct,
                    members=members,
                    parity_protected=parity,
                    autotrim="nvme" in str(members),
                    compression=md_compression(str(resolved_fstype or mounts), mount_path),
                )
            )

        # 2. Discover bcache and block device mounts
        for m in mounts:
            dev = m.get("device", "")
            mp = m.get("mountpoint", "")
            fstype = m.get("fstype", "")
            if dev.startswith("/dev/bcache") or (
                dev.startswith(("/dev/sd", "/dev/nvme", "/dev/mapper")) and not dev.startswith("/dev/mmcblk")
            ):
                if self._is_os_overlay_or_emmc(mp) or mp in claimed_mount_paths:
                    continue
                if any(p.id == os.path.basename(dev) or p.mountpoint == mp for p in pools):
                    continue

                try:
                    u = shutil.disk_usage(mp)
                    tot, usd, fre = u.total, u.used, u.free
                except Exception:
                    continue

                if tot < 20 * 1024 * 1024 * 1024:
                    continue

                pct = round(usd / tot * 100, 1) if tot > 0 else 0.0

                pool_members = []
                for d_name, d_rec in hal_disks.items():
                    if d_rec.role == "cache" or "nvme" in d_name:
                        pool_members.append(d_rec)
                if not pool_members:
                    pool_members = list(hal_disks.values())

                dev_base = os.path.basename(dev)
                p_name = (
                    "Fast Storage & Apps Pool (Btrfs)"
                    if "bcache" in dev or "nvme" in dev
                    else f"{dev_base} ({fstype.upper()})"
                )
                pools.append(
                    StoragePool(
                        id=dev_base,
                        name=p_name,
                        pool_type="btrfs" if fstype == "btrfs" else "single",
                        fs_type=fstype,
                        fs_profile="single",
                        status="HEALTHY",
                        mountpoint=mp,
                        total_bytes=tot,
                        used_bytes=usd,
                        free_bytes=fre,
                        used_pct=pct,
                        members=pool_members,
                        parity_protected=True,
                    )
                )

        # 3. Discover OpenZFS pools
        code, zout, _ = self._run_cmd(["zpool", "list", "-Hp", "-o", "name,size,alloc,free,health"])
        if code == 0 and zout.strip():
            for line in zout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 5:
                    zp_name = parts[0].strip()
                    zp_size, zp_alloc, zp_free, zp_health = (
                        parts[1].strip(),
                        parts[2].strip(),
                        parts[3].strip(),
                        parts[4].strip(),
                    )
                    try:
                        z_total = int(zp_size) if zp_size.isdigit() else 0
                        z_used = int(zp_alloc) if zp_alloc.isdigit() else 0
                        z_free = int(zp_free) if zp_free.isdigit() else 0
                        z_pct = round(z_used / z_total * 100, 1) if z_total > 0 else 0.0
                    except Exception:
                        z_total, z_used, z_free, z_pct = 0, 0, 0, 0.0

                    _, zmnt, _ = self._run_cmd(["zfs", "get", "-Hp", "-o", "value", "mountpoint", zp_name])
                    z_mount = zmnt.strip() if zmnt.strip() and zmnt.strip() != "none" else f"/{zp_name}"

                    _, zstat, _ = self._run_cmd(["zpool", "status", zp_name])
                    z_profile = "single"
                    zstat_l = zstat.lower()
                    if "raidz3" in zstat_l:
                        z_profile = "raidz3"
                    elif "raidz2" in zstat_l:
                        z_profile = "raidz2"
                    elif "raidz1" in zstat_l:
                        z_profile = "raidz1"
                    elif "mirror" in zstat_l:
                        z_profile = "mirror"

                    z_members = self._parse_zpool_members(zp_name)

                    pools.append(
                        StoragePool(
                            id=zp_name,
                            name=zp_name,
                            pool_type="zfs_raid"
                            if z_profile in ("raidz1", "raidz2", "raidz3")
                            else ("zfs_mirror" if z_profile == "mirror" else "zfs_single"),
                            fs_type="zfs",
                            fs_profile=z_profile,
                            status="HEALTHY" if zp_health == "ONLINE" else zp_health,
                            mountpoint=z_mount,
                            total_bytes=z_total,
                            used_bytes=z_used,
                            free_bytes=z_free,
                            used_pct=z_pct,
                            members=z_members,
                            parity_protected=z_profile in ("raidz1", "raidz2", "raidz3", "mirror"),
                            autotrim=True,
                            compression=pool_compression("zfs", z_mount, zp_name),
                        )
                    )

        # 4. Standard pool at self._pool_path
        if not is_overlay:
            total, used, free = 0, 0, 0
            try:
                u = shutil.disk_usage(self._pool_path if os.path.exists(self._pool_path) else "/")
                total, used, free = u.total, u.used, u.free
            except Exception:
                ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_pools")
            pct = round(used / total * 100, 1) if total > 0 else 0.0

            members = list(hal_disks.values()) if hal_disks else self._discover_hal_disks()

            fs_type, profile = self._main_pool_facts()
            parity_protected = profile in ("raid1", "raid10", "raid5", "raid6")

            if not any(p.mountpoint == self._pool_path for p in pools):
                pools.insert(
                    0,
                    StoragePool(
                        id="default_pool",
                        name="Primary Storage Pool",
                        pool_type="btrfs_raid" if parity_protected or profile == "raid0" else "single",
                        fs_type=fs_type,
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
                        compression=pool_compression(fs_type, self._pool_path),
                    ),
                )
        elif not pools:
            try:
                u = shutil.disk_usage(self._pool_path if os.path.exists(self._pool_path) else "/")
                total, used, free = u.total, u.used, u.free
            except Exception:
                total, used, free = 0, 0, 0
            pct = round(used / total * 100, 1) if total > 0 else 0.0
            pools.append(
                StoragePool(
                    id="system_flash",
                    name="System Boot Flash (eMMC)",
                    pool_type="os_boot",
                    fs_type="overlay",
                    status="HEALTHY",
                    mountpoint=self._pool_path,
                    total_bytes=total,
                    used_bytes=used,
                    free_bytes=free,
                    used_pct=pct,
                    members=[],
                    parity_protected=False,
                )
            )

        return pools

    def _share_figures(self, path: str) -> dict:
        """Used, free and total for a share card: the folder's own where the filesystem keeps it
        (usage_is_own), else the pool's, which the card shows as free space only (SET-14, B35)."""
        try:
            u = shutil.disk_usage(path if os.path.exists(path) else self._pool_path)
            tot, usd, fre = u.total, u.used, u.free
        except OSError:
            tot, usd, fre = 0, 0, 0
        own = own_usage(path, self._run_cmd) if os.path.isdir(path) else None
        if own:
            usd, limit = own
            fre = max(0, limit - usd) if limit else fre
            tot = usd + fre
        pct = round(usd / tot * 100, 1) if tot > 0 else 0.0
        return {"used_bytes": usd, "free_bytes": fre, "total_bytes": tot, "used_pct": pct, "usage_is_own": bool(own)}

    def list_shares(self) -> list[NetworkShare]:
        shares_map: dict[str, NetworkShare] = {}
        # 1. Inspect Samba Engine shares
        try:
            from backend.services.samba_engine import get_samba_engine

            engine = get_samba_engine()
            samba_shares = engine.list_shares()
            for s in samba_shares:
                mount_p = s.path
                fig = self._share_figures(mount_p)

                shares_map[s.name] = NetworkShare(
                    name=s.name,
                    comment=s.comment or "Kiboto Managed Share",
                    security="public" if s.guest_ok else "private",
                    export_smb=True,
                    export_nfs=False,
                    export_webdav=True,
                    cache_mode="none",
                    mountpoint=mount_p,
                    **fig,
                )
        except Exception as e:
            logger.debug("[PAL] SambaEngine shares query fallback: %s", e)

        # 2. Inspect NFS Engine exports
        try:
            from backend.services.nfs_engine import get_nfs_engine

            nfs_engine = get_nfs_engine()
            for n in nfs_engine.list_exports():
                if n.name in shares_map:
                    shares_map[n.name].export_nfs = True
                else:
                    mount_p = n.path
                    fig = self._share_figures(mount_p)

                    shares_map[n.name] = NetworkShare(
                        name=n.name,
                        comment=n.comment or "Kiboto Managed NFS Export",
                        security="public" if n.clients == "*" else "private",
                        export_smb=False,
                        export_nfs=True,
                        export_webdav=False,
                        cache_mode="none",
                        mountpoint=mount_p,
                        **fig,
                    )
        except Exception as e:
            logger.debug("[PAL] NfsEngine exports query fallback: %s", e)

        if shares_map:
            return list(shares_map.values())

        # 3. Filesystem directory fallback
        if os.path.isdir(self._pool_path):
            try:
                for entry in sorted(os.listdir(self._pool_path)):
                    sub_p = os.path.join(self._pool_path, entry)
                    if os.path.isdir(sub_p) and not entry.startswith((".", "@")):
                        fig = self._share_figures(sub_p)
                        shares_map[entry] = NetworkShare(
                            name=entry,
                            comment="Managed Linux Share",
                            security="public",
                            export_smb=True,
                            export_nfs=False,
                            export_webdav=True,
                            cache_mode="none",
                            mountpoint=sub_p,
                            **fig,
                        )
            except Exception as e:
                logger.debug(f"[PAL] Error listing generic shares: {e}")
        return list(shares_map.values())

    def _must(self, cmd: list[str], what: str) -> str:
        """Runs a step of pool creation; a failure stops it with the tool's own message."""
        code, out, err = self._run_cmd(cmd)
        if code != 0:
            raise RuntimeError(f"{what} failed ({code}): {(err or out or 'no output')[:300]}")
        return out

    def create_pool(
        self,
        name: str,
        fs_type: str,
        profile: str,
        disks: list[str],
        mountpoint: str,
    ) -> dict[str, Any]:
        """Creates a multi-device Btrfs, OpenZFS, ext4, or XFS storage pool."""
        if not disks:
            raise ValueError("At least one disk must be specified to create a storage pool")

        resolved_disks = [self._resolve_disk_path(d) for d in disks]
        profile_lower = profile.lower()
        fs_lower = fs_type.lower()

        # Validate drive counts for RAID profiles
        if fs_lower == "zfs":
            if profile_lower == "raidz1" and len(resolved_disks) < 3:
                raise ValueError("OpenZFS RAIDZ1 requires at least 3 disks (single parity)")
            elif profile_lower == "raidz2" and len(resolved_disks) < 4:
                raise ValueError("OpenZFS RAIDZ2 requires at least 4 disks (dual parity)")
            elif profile_lower == "raidz3" and len(resolved_disks) < 5:
                raise ValueError("OpenZFS RAIDZ3 requires at least 5 disks (triple parity)")
            elif profile_lower in ("mirror", "raid1") and len(resolved_disks) < 2:
                raise ValueError("OpenZFS Mirror requires at least 2 disks")
        else:
            if profile_lower in ("raid1", "raid0") and len(resolved_disks) < 2:
                raise ValueError(f"{profile.upper()} requires at least 2 disks")
            if profile_lower == "raid10" and len(resolved_disks) < 4:
                raise ValueError("RAID10 requires at least 4 disks")

        target_mount = mountpoint.strip() or os.path.join(self._pool_path, name)
        try:
            os.makedirs(target_mount, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create target mount dir {target_mount}: {e}")

        if fs_lower == "zfs":
            # ashift=12 (4Kn/512e modern sector alignment), zstd compression, posixacl, xattr=sa
            vdev_type = profile_lower if profile_lower in ("raidz1", "raidz2", "raidz3", "mirror") else ""
            vdev_args = [vdev_type] + resolved_disks if vdev_type else resolved_disks
            cmd = [
                "zpool",
                "create",
                "-f",
                "-o",
                "ashift=12",
                "-O",
                "compression=zstd",
                "-O",
                "acltype=posixacl",
                "-O",
                "xattr=sa",
                "-O",
                "atime=off",
                "-m",
                target_mount,
                name,
            ] + vdev_args
            self._must(cmd, "zpool create")

        elif fs_lower == "btrfs":
            cmd = ["mkfs.btrfs", "-f", "-L", name, "-m", profile_lower, "-d", profile_lower] + resolved_disks
            self._must(cmd, "mkfs.btrfs")

            # Mount with modern zstd compression and fast noatime
            mount_cmd = ["mount", "-o", "compress=zstd:1,noatime,space_cache=v2", resolved_disks[0], target_mount]
            self._must(mount_cmd, "mount")

            # Create default subvolumes for shares and snapshots
            self._run_cmd(["btrfs", "subvolume", "create", os.path.join(target_mount, "@shares")])
            self._run_cmd(["btrfs", "subvolume", "create", os.path.join(target_mount, "@snapshots")])

        elif fs_lower == "ext4":
            self._must(["mkfs.ext4", "-F", "-L", name, resolved_disks[0]], "mkfs.ext4")
            self._must(["mount", resolved_disks[0], target_mount], "mount")

        elif fs_lower == "xfs":
            self._must(["mkfs.xfs", "-f", "-L", name, resolved_disks[0]], "mkfs.xfs")
            self._must(["mount", resolved_disks[0], target_mount], "mount")

        return {
            "status": "provisioned",
            "name": name,
            "fs_type": fs_lower,
            "profile": profile_lower,
            "mountpoint": target_mount,
            "disks": resolved_disks,
            "created_at": time.time(),
        }

    def rename_pool(self, pool_id: str, new_name: str) -> dict[str, Any]:
        """Renames a storage pool (ZFS export/import, Btrfs label) and creates compatibility symlink."""
        if not new_name or not new_name.strip():
            raise ValueError("New pool name cannot be empty")
        clean_name = new_name.strip()
        if pool_id == clean_name:
            return {
                "status": "unchanged",
                "pool_id": pool_id,
                "name": clean_name,
                "message": "Pool name unchanged",
            }

        pool = self.resolve_pool(pool_id)
        pool_id = pool.id
        if pool.fs_type == "zfs":
            exp_code, _, exp_err = self._run_cmd(["zpool", "export", pool_id])
            if exp_code != 0 and exp_code != 127:
                raise RuntimeError(f"Failed to export zpool '{pool_id}': {exp_err or 'active I/O or busy'}")

            imp_code, _, imp_err = self._run_cmd(["zpool", "import", pool_id, clean_name])
            if imp_code != 0 and imp_code != 127:
                self._run_cmd(["zpool", "import", pool_id])
                raise RuntimeError(f"Failed to import zpool as '{clean_name}': {imp_err}")

            old_mnt = child_path(self._pool_path, pool_id)  # names, never paths (the API checks them too)
            new_mnt = child_path(self._pool_path, clean_name)
            try:
                if os.path.exists(old_mnt) and not os.path.islink(old_mnt):
                    try:
                        os.rmdir(old_mnt)
                    except Exception:
                        ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.rename_pool")
                if not os.path.exists(old_mnt):
                    os.symlink(new_mnt, old_mnt)
                    logger.info("[PAL] Created compatibility symlink %s -> %s", old_mnt, new_mnt)
            except Exception as e:
                logger.warning("[PAL] Could not create compatibility symlink %s -> %s: %s", old_mnt, new_mnt, e)

            return {
                "status": "renamed",
                "old_name": pool_id,
                "new_name": clean_name,
                "fs_type": "zfs",
                "mountpoint": new_mnt,
                "compat_symlink": old_mnt,
            }

        # 2. btrfs: the label is the pool's name, set on the pool's own folder. Nothing else can be
        # renamed here, and a rename that did not happen is not reported as one.
        if pool.fs_type != "btrfs" or not pool.mountpoint:
            raise ValueError(f"{pool.name} is {pool.fs_type}: only ZFS and btrfs pools can be renamed here.")
        code, out, err = self._run_cmd(["btrfs", "filesystem", "label", pool.mountpoint, clean_name])
        if code != 0:
            raise RuntimeError(f"{pool.name} could not be renamed: {(err or out or 'the label was not set').strip()}")
        return {
            "status": "renamed",
            "old_name": pool.name,
            "new_name": clean_name,
            "fs_type": "btrfs",
            "mountpoint": pool.mountpoint,
            "compat_symlink": None,
        }

    def destroy_pool(self, pool_id: str) -> dict[str, Any]:
        """Unmounts the pool that is named. It unmounted "<pool folder>/<id>", which for most
        pools is no folder at all, and answered "destroyed" whatever happened."""
        pool = self.resolve_pool(pool_id)
        if not pool.mountpoint:
            raise RuntimeError(f"{pool.name} is not mounted, so there is nothing to remove.")
        code, out, err = self._run_cmd(["umount", "-f", pool.mountpoint])
        if code != 0:
            raise RuntimeError(f"{pool.name} could not be unmounted: {(err or out or 'it is in use').strip()}")
        return {"status": "destroyed", "pool_id": pool.id, "mountpoint": pool.mountpoint, "unmount_code": code}

    def erase_plan(self, pool_id: str) -> dict[str, Any]:
        """The drives a pool's own tool lists, each confirmed by its on-disk label (S29)."""
        from backend.hardware.pal import pool_erase

        try:
            return pool_erase.plan(self.resolve_pool(pool_id), self._run_cmd)
        except pool_erase.EraseRefused as e:
            raise RuntimeError(str(e)) from e

    def erase_pool(self, pool_id: str) -> dict[str, Any]:
        """Deletes the pool and erases exactly the drives the plan confirmed (S29)."""
        from backend.hardware.pal import pool_erase

        try:
            p = pool_erase.plan(self.resolve_pool(pool_id), self._run_cmd)
            erased = pool_erase.execute(p, self._run_cmd)
        except pool_erase.EraseRefused as e:
            raise RuntimeError(str(e)) from e
        logger.warning("[Storage] pool %s deleted, drives erased: %s", p["pool"], erased)
        return {"status": "erased", "pool_id": p["pool"], "drives": erased}

    def export_pool(self, pool_id: str, force: bool = False) -> dict[str, Any]:
        """Safely flushes dirty write cache, checks active file handles, and exports or unmounts a storage pool."""
        pool = self.resolve_pool(pool_id)
        pool_id = pool.id
        is_zfs = pool.fs_type == "zfs"

        target_mount = pool.mountpoint or ""
        if is_zfs:
            c_mnt, o_mnt, _ = self._run_cmd(["zfs", "get", "-H", "-o", "value", "mountpoint", pool_id])
            if c_mnt == 0 and o_mnt.strip() and o_mnt.strip() != "none":
                target_mount = o_mnt.strip()

        # Check for active file handles holding the mountpoint
        active_handles = []
        if os.path.exists(target_mount):
            c_fu, o_fu, _ = self._run_cmd(["fuser", "-m", target_mount])
            if c_fu == 0 and o_fu.strip():
                pids = o_fu.strip().split()
                active_handles.extend([f"PID {p}" for p in pids[:10]])

        if active_handles and not force:
            raise RuntimeError(
                f"Storage pool '{pool_id}' has {len(active_handles)} active process(es) holding open handles: "
                f"{', '.join(active_handles)}. Specify force=true to unmount and export anyway."
            )

        # Flush filesystem write caches
        self._run_cmd(["sync"])

        if is_zfs:
            exp_cmd = ["zpool", "export", "-f", pool_id] if force else ["zpool", "export", pool_id]
            c_exp, _, err_exp = self._run_cmd(exp_cmd)
            if c_exp != 0:
                raise RuntimeError(f"Failed to export zpool '{pool_id}': {err_exp or 'busy or in use'}")
            fs_type = "zfs"
        else:
            um_cmd = ["umount", "-f", target_mount] if force else ["umount", target_mount]
            c_um, _, err_um = self._run_cmd(um_cmd)
            if c_um != 0:
                raise RuntimeError(f"Failed to unmount pool '{pool_id}': {err_um or 'busy or in use'}")
            fs_type = "generic"

        return {
            "status": "exported",
            "pool_id": pool_id,
            "fs_type": fs_type,
            "mountpoint": target_mount,
            "safe_to_disconnect": True,
            "message": f"Storage pool '{pool_id}' safely exported and flushed. Safe to disconnect cable.",
        }

    def import_pool(self, pool_id: str, fs_type: str = "zfs", target_mount: str | None = None) -> dict[str, Any]:
        """Imports an external storage pool from an attached enclosure."""
        fs_lower = fs_type.lower()
        if fs_lower == "zfs":
            code, out, err = self._run_cmd(["zpool", "import", "-f", pool_id])
            if code != 0:
                raise RuntimeError(f"Failed to import zpool '{pool_id}': {err or out}")
            return {
                "status": "imported",
                "pool_id": pool_id,
                "fs_type": "zfs",
                "message": f"OpenZFS pool '{pool_id}' successfully imported.",
            }
        else:
            self._run_cmd(["btrfs", "device", "scan"])
            mnt = target_mount or os.path.join(self._pool_path, pool_id)
            os.makedirs(mnt, exist_ok=True)
            code, out, err = self._run_cmd(["mount", "-L", pool_id, mnt])
            if code != 0:
                code, out, err = self._run_cmd(["mount", f"/dev/disk/by-label/{pool_id}", mnt])
            return {
                "status": "imported" if code == 0 else "error",
                "pool_id": pool_id,
                "fs_type": fs_lower,
                "mountpoint": mnt,
                "message": f"Pool '{pool_id}' imported at {mnt}" if code == 0 else f"Failed to mount: {err}",
            }

    def discover_external_pools(self) -> list[dict[str, Any]]:
        """Scans for unmounted external storage pools available to import."""
        discovered = []
        code, out, _ = self._run_cmd(["zpool", "import"])
        if code == 0 and out.strip():
            current_pool = {}
            for line in out.splitlines():
                line_str = line.strip()
                if line_str.startswith("pool:"):
                    if current_pool.get("pool_id"):
                        discovered.append(current_pool)
                    current_pool = {
                        "pool_id": line_str.split(":", 1)[1].strip(),
                        "fs_type": "zfs",
                        "status": "ONLINE",
                        "detachable": True,
                    }
                elif line_str.startswith("id:") and current_pool:
                    current_pool["numeric_id"] = line_str.split(":", 1)[1].strip()
                elif line_str.startswith("state:") and current_pool:
                    current_pool["status"] = line_str.split(":", 1)[1].strip()
            if current_pool.get("pool_id"):
                discovered.append(current_pool)

        return discovered

    def create_share(
        self,
        name: str,
        path: str,
        comment: str = "",
        security: str = "public",
        read_only: bool = False,
        export_smb: bool = True,
        export_nfs: bool = False,
        quota_gb: int = 0,
        user_permissions: dict[str, str] | None = None,
        nfs_squash: str = "root_squash",
        nfs_anonuid: int = 1000,
        nfs_anongid: int = 1000,
        nfs_sync: bool = True,
        nfs_clients: str = "",
    ) -> dict[str, Any]:
        """Provisions a network share and syncs with SambaEngine and NfsEngine."""
        from backend.services.samba_engine import validate_share_path

        full_path = validate_share_path(path if path else os.path.join(self._pool_path, name))
        if export_nfs:  # refuse bad NFS settings before anything is created
            from backend.services.nfs_engine import NfsExportRule, home_network

            try:
                NfsExportRule(
                    name=name,
                    path=full_path,
                    clients=nfs_clients.strip() or home_network(),
                    squash=nfs_squash or "root_squash",
                    comment=comment,
                )
            except Exception as e:
                raise ValueError(f"Invalid NFS export settings: {e}") from e
        self._make_share_dir(full_path)
        quota = fs_quota.apply(full_path, quota_gb * 1024**3) if quota_gb > 0 else None  # FEAT-10

        user_perms = user_permissions or {}
        valid_users = None
        read_list = None
        write_list = None

        if user_perms:
            rw_users = [u for u, p in user_perms.items() if p == "rw"]
            ro_users = [u for u, p in user_perms.items() if p == "ro"]
            all_allowed = rw_users + ro_users
            if all_allowed:
                valid_users = " ".join(all_allowed)
            if ro_users:
                read_list = " ".join(ro_users)
            if rw_users:
                write_list = " ".join(rw_users)

        if export_smb:
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
                    quota_gb=quota_gb if quota_gb > 0 else None,
                    valid_users=valid_users,
                    read_list=read_list,
                    write_list=write_list,
                )
                engine.add_or_update_share(share_cfg)
            except ValueError:
                raise  # refused settings (SEC-06): stop here, before anything is exported over NFS
            except Exception as e:
                logger.warning(f"[PAL] SambaEngine registration failed: {e}")

        if export_nfs:
            from backend.services.nfs_engine import NfsExportRule, home_network

            try:
                rule = NfsExportRule(
                    name=name,
                    path=full_path,
                    clients=nfs_clients.strip() or home_network(),
                    permission="ro" if read_only else "rw",
                    squash=nfs_squash or "root_squash",
                    anonuid=nfs_anonuid,
                    anongid=nfs_anongid,
                    sync_mode="sync" if nfs_sync else "async",
                    comment=comment,
                )
            except Exception as e:  # pydantic ValidationError: a refused setting
                raise ValueError(f"Invalid NFS export settings: {e}") from e
            try:
                from backend.services.nfs_engine import get_nfs_engine

                get_nfs_engine().add_or_update_export(rule)
            except Exception as e:
                logger.warning(f"[PAL] NfsEngine registration failed: {e}")

        return {
            "status": "created",
            "name": name,
            "mountpoint": full_path,
            "comment": comment,
            "security": security,
            "read_only": read_only,
            "export_smb": export_smb,
            "export_nfs": export_nfs,
            "quota_gb": quota_gb,
            "quota_enforcement": quota,
            "user_permissions": user_perms,
        }

    def delete_share(self, name: str) -> dict[str, Any]:
        """Deletes a network share from Samba and NFS configurations."""
        try:
            from backend.services.samba_engine import get_samba_engine

            engine = get_samba_engine()
            engine.remove_share(name)
        except Exception as e:
            logger.warning(f"[PAL] Failed deleting share from SambaEngine: {e}")

        try:
            from backend.services.nfs_engine import get_nfs_engine

            nfs_engine = get_nfs_engine()
            nfs_engine.remove_export(name)
        except Exception as e:
            logger.warning(f"[PAL] Failed deleting share from NfsEngine: {e}")

        return {"status": "deleted", "name": name}

    def create_snapshot(
        self,
        pool_id: str,
        subvol_name: str,
        snapshot_name: str,
        readonly: bool = True,
        worm_mode: str | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        """Creates an atomic Btrfs subvolume snapshot with optional Two-Tier WORM immutability."""
        src_path = child_path(os.path.join(self._pool_path, "@shares"), subvol_name)
        if not os.path.exists(src_path):
            src_path = child_path(self._pool_path, subvol_name)

        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        try:
            os.makedirs(snaps_dir, exist_ok=True)
        except OSError as e:
            logger.warning(f"[PAL] Could not pre-create snapshots dir {snaps_dir}: {e}")
        dest_path = child_path(snaps_dir, snapshot_name)

        # Force readonly for WORM snapshots
        if worm_mode in ("compliance", "governance"):
            readonly = True

        dataset = zfs_dataset_at(src_path)
        if dataset:  # ZFS snapshots are always read-only; WORM ones are also held
            full = f"{dataset}@{zfs_snapshot_part(snapshot_name)}"
            code, out, err = self._run_cmd(["zfs", "snapshot", "-o", f"{ZFS_NAME_PROP}={snapshot_name}", full])
            if code == 0 and worm_mode in ("compliance", "governance"):
                hold, _, herr = self._run_cmd(["zfs", "hold", ZFS_HOLD_TAG, full])
                if hold:
                    logger.warning("[PAL] %s: no hold (%s); the lock is Kiboto's own only", full, herr)
            dest_path = os.path.join(src_path, ".zfs", "snapshot", zfs_snapshot_part(snapshot_name))
            readonly = True
        elif fs_of(src_path) == "zfs":
            code, out, err = (
                1,
                "",
                f"{subvol_name} is a folder, not a ZFS dataset of its own; it can't be snapshotted alone.",
            )
        else:
            cmd = ["btrfs", "subvolume", "snapshot"]
            if readonly:
                cmd.append("-r")
            cmd.extend([src_path, dest_path])
            code, out, err = self._run_cmd(cmd)

        now = time.time()
        retention_until = None
        if worm_mode in ("compliance", "governance"):
            days = retention_days if (retention_days and retention_days > 0) else 30
            retention_until = now + (days * 86400)
            worm_meta = {
                "snapshot_name": snapshot_name,
                "pool_id": pool_id,
                "subvol_name": subvol_name,
                "worm_mode": worm_mode.lower(),
                "created_at": now,
                "retention_until": retention_until,
            }
            meta_path = os.path.join(snaps_dir, f".{snapshot_name}.worm.json")
            try:
                atomic_write_json(meta_path, worm_meta, indent=2)
            except Exception as e:
                logger.warning(f"[PAL] Failed saving WORM metadata: {e}")

        return {
            "status": "created" if code == 0 else "error",  # 127 = btrfs missing: not created (REL-4)
            "source": src_path,
            "snapshot": dest_path,
            "readonly": readonly,
            "worm_mode": worm_mode,
            "retention_until": retention_until,
            "code": code,
            "output": out or err,
        }

    def list_snapshots(self, pool_id: str) -> list[dict[str, Any]]:
        """Lists active Btrfs subvolume snapshots with WORM immutability metadata."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        snapshots: list[dict[str, Any]] = []
        if os.path.isdir(snaps_dir):
            try:
                for entry in sorted(os.listdir(snaps_dir)):
                    if entry.startswith("."):
                        continue
                    p = os.path.join(snaps_dir, entry)
                    if os.path.isdir(p):
                        stat = os.stat(p)
                        item = {
                            "name": entry,
                            "path": p,
                            "created_at": stat.st_mtime,
                            "pool_id": pool_id,
                            "worm_mode": None,
                            "retention_until": None,
                            "is_immutable": False,
                        }
                        self._read_worm(item)
                        snapshots.append(item)
            except Exception as e:
                logger.debug(f"[PAL] Snapshot list error: {e}")
        return snapshots + self._zfs_snapshots(pool_id)

    def _read_worm(self, item: dict[str, Any]) -> None:
        """Fills in a snapshot's WORM lock from its metadata file, when it has one."""
        meta_path = os.path.join(self._pool_path, "@snapshots", f".{item['name']}.worm.json")
        if not os.path.isfile(meta_path):
            return
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            item["worm_mode"] = meta.get("worm_mode")
            item["retention_until"] = meta.get("retention_until")
            item["is_immutable"] = (meta.get("retention_until") or 0) > time.time()
        except Exception:
            ignored("backend.hardware.pal_storage.GenericLinuxStorageAdapter.list_snapshots")

    def _zfs_snapshots(self, pool_id: str) -> list[dict[str, Any]]:
        """Snapshots of the ZFS datasets mounted inside this pool, under their own names, with
        the path ZFS shows them at (.zfs/snapshot in the dataset)."""
        from backend.hardware.pal.base import storage_tools

        if not storage_tools()["zfs"]:
            return []
        code, out, _ = self._run_cmd(
            ["zfs", "list", "-H", "-p", "-t", "snapshot", "-o", f"name,creation,{ZFS_NAME_PROP}"]
        )
        if code:
            return []
        mounts, root = zfs_mounts(), os.path.realpath(self._pool_path).rstrip("/")
        items = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) < 3 or "@" not in parts[0]:
                continue
            dataset, part = parts[0].split("@", 1)
            mnt = mounts.get(dataset, "")
            if not (mnt == root or mnt.startswith(root + "/")):
                continue
            item = {
                "name": parts[2] if parts[2] not in ("", "-") else part,
                "path": os.path.join(mnt, ".zfs", "snapshot", part),
                "created_at": float(parts[1]) if parts[1].isdigit() else 0.0,
                "pool_id": pool_id,
                "worm_mode": None,
                "retention_until": None,
                "is_immutable": False,
                "zfs": parts[0],
            }
            self._read_worm(item)
            items.append(item)
        return items

    def readable_snapshot_path(self, snap: dict[str, Any]) -> str:
        """Where a snapshot's files can be read. ZFS shows a snapshot at .zfs/snapshot/<name> by
        mounting it on first access, which the kernel doesn't do inside a container: there the
        folder reads as empty, and a rollback from it removed the share's files. A ZFS snapshot
        whose folder reads as empty is mounted read-only under SNAPSHOT_VIEWS and read there;
        it is unmounted before the snapshot is deleted."""
        path, name = str(snap.get("path") or ""), str(snap.get("zfs") or "")
        if not name:
            return path
        try:
            if os.listdir(path):
                return path
        except OSError:  # no folder there either: the mount below is the way to read it
            logger.debug("[PAL] %s can't be listed; mounting the snapshot instead", path)
        view = self._view_dir(name)
        if is_mount_point(view):
            return view
        os.makedirs(view, mode=0o700, exist_ok=True)
        code, _, err = self._run_cmd(["mount", "-t", "zfs", "-o", "ro", name, view])
        if code:
            raise RuntimeError(f"The snapshot can't be read here ({(err or '').strip() or 'mount failed'}).")
        return view

    @staticmethod
    def _view_dir(zfs_name: str) -> str:
        return os.path.join(SNAPSHOT_VIEWS, re.sub(r"[^A-Za-z0-9._-]", "_", zfs_name))

    def _release_view(self, zfs_name: str) -> None:
        view = self._view_dir(zfs_name)
        if is_mount_point(view):
            self._run_cmd(["umount", view])
        with contextlib.suppress(OSError):
            os.rmdir(view)

    def delete_snapshot(
        self,
        pool_id: str,
        snapshot_name: str,
        break_glass: bool = False,
        reason: str = "",
    ) -> dict[str, Any]:
        """Deletes a Btrfs subvolume snapshot, strictly enforcing Two-Tier WORM immutability."""
        snaps_dir = os.path.join(self._pool_path, "@snapshots")
        target_path = child_path(snaps_dir, snapshot_name)  # never a live subvolume via ../ (WORM)
        meta_path = os.path.join(snaps_dir, f".{snapshot_name}.worm.json")

        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                mode = (meta.get("worm_mode") or "").lower()
                retention_until = meta.get("retention_until") or 0
                now = time.time()
                if now < retention_until:
                    if mode == "compliance":
                        raise PlatformCapabilityError(
                            f"Compliance WORM lock active: Snapshot '{snapshot_name}' cannot be deleted until retention expires on {time.ctime(retention_until)}."
                        )
                    elif mode == "governance" and not break_glass:
                        raise PlatformCapabilityError(
                            f"Governance WORM lock active: Snapshot '{snapshot_name}' requires Break-Glass authorization and audit justification to delete."
                        )
            except PlatformCapabilityError:
                raise
            except Exception as e:
                logger.warning(f"[PAL] Error reading WORM metadata during delete: {e}")

        # If break_glass was invoked for governance snapshot, log security audit event
        if break_glass:
            try:
                from backend.users_db import log_security_event

                log_security_event(
                    event_type="worm_break_glass_delete",
                    status="success",
                    details={"snapshot": snapshot_name, "pool_id": pool_id, "reason": reason},
                )
            except Exception as e:
                logger.warning(f"[PAL] Security audit log error: {e}")

        zsnap = next((s for s in self._zfs_snapshots(pool_id) if s["name"] == snapshot_name), None)
        if zsnap:
            self._release_view(zsnap["zfs"])  # a mounted snapshot can't be destroyed
            self._run_cmd(["zfs", "release", ZFS_HOLD_TAG, zsnap["zfs"]])  # fails when there was no hold
            code, out, err = self._run_cmd(["zfs", "destroy", zsnap["zfs"]])
            target_path = zsnap["path"]
        else:
            code, out, err = self._run_cmd(["btrfs", "subvolume", "delete", target_path])
        if os.path.isfile(meta_path) and code in (0, 127):
            try:
                os.remove(meta_path)
            except OSError:
                pass

        return {
            "status": "deleted" if code in (0, 127) else "error",
            "snapshot": snapshot_name,
            "path": target_path,
            "code": code,
        }

    def restore_snapshot(self, pool_id: str, snapshot_name: str, target_subvol: str = "") -> dict[str, Any]:
        """Restores or rolls back a Btrfs subvolume snapshot into active subvolume path."""
        snap_path = child_path(os.path.join(self._pool_path, "@snapshots"), snapshot_name)
        if not os.path.exists(snap_path):
            return {"status": "error", "message": f"Snapshot {snapshot_name} not found at {snap_path}", "code": 1}

        subvol = target_subvol.strip()
        if not subvol:
            subvol = snapshot_name.split("_")[0] if "_" in snapshot_name else "restored_" + snapshot_name

        dest_dir = os.path.join(self._pool_path, "@shares")
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except OSError:
            pass
        dest_path = child_path(dest_dir, subvol)

        archived_path = None
        if os.path.exists(dest_path):
            ts = int(time.time())
            archived_path = f"{dest_path}.pre_restore.{ts}"
            try:
                os.rename(dest_path, archived_path)
            except OSError as e:
                logger.warning(f"[PAL] Could not archive pre-existing subvolume {dest_path}: {e}")

        # Btrfs snapshot restore creates a writable subvolume clone from the read-only snapshot
        cmd = ["btrfs", "subvolume", "snapshot", snap_path, dest_path]
        code, out, err = self._run_cmd(cmd)

        return {
            "status": "restored" if code in (0, 127) else "error",
            "snapshot": snap_path,
            "target": dest_path,
            "archived_previous": archived_path,
            "code": code,
            "output": out or err,
        }

    def get_pool_path(self, pool_id: str) -> str:
        """Returns root mountpoint for a generic Linux storage pool."""
        if not pool_id or pool_id in ("default_pool", "default"):
            return self._pool_path
        cand = os.path.join(self._pool_path, pool_id)
        return cand if os.path.exists(cand) else self._pool_path
