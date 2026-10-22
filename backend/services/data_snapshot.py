"""
Pre-update snapshots of the ZettNAS data folder (OPS-03).

The updater takes one right after stopping the old container and restores it
when it rolls back, so the previous version never runs against databases the
new version already migrated. Snapshots live in data/backups/pre-update/; the
newest KEEP are kept.

Not included: the AI search index (rag_index.db, rebuildable and large),
caches, and the backups folder itself.
"""

import json
import logging
import os
import shutil
import sqlite3
import stat
import time
from typing import Any, Optional

logger = logging.getLogger("zettnas.data_snapshot")

SNAPSHOT_SUBDIR = os.path.join("backups", "pre-update")
KEEP = 3
INCLUDE_DIRS = ("rclone", "samba", "sftp", "nfs", "stacks")
SKIP_PREFIXES = ("rag_index.db",)
SKIP_SUFFIXES = (".png", ".bmp", ".jpg", ".py", ".tmp", "-wal", "-shm", ".lock")
MANIFEST = "manifest.json"


def _wanted_file(name: str) -> bool:
    return not name.startswith(SKIP_PREFIXES) and not name.endswith(SKIP_SUFFIXES)


def _copy_db(src: str, dst: str) -> None:
    """Consistent copy of a SQLite file (includes anything still in its WAL)."""
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30.0)
    d = sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()


def snapshot_root(data_dir: str) -> str:
    return os.path.join(data_dir, SNAPSHOT_SUBDIR)


def _skip_special_files(directory: str, names: list[str]) -> list[str]:
    """Sockets, FIFOs and device nodes can't be copied (e.g. Samba's msg.sock); they hold no data."""
    skip = []
    for n in names:
        try:
            mode = os.lstat(os.path.join(directory, n)).st_mode
        except OSError:
            continue
        if stat.S_ISSOCK(mode) or stat.S_ISFIFO(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
            skip.append(n)
    return skip


def take_snapshot(
    data_dir: str, label: str = "", extra: dict[str, Any] | None = None, protect: str | None = None
) -> str:
    root = snapshot_root(data_dir)
    safe_label = "".join(c if c.isalnum() or c in ".-_" else "_" for c in label)[:40]
    dest = os.path.join(root, time.strftime("%Y%m%d-%H%M%S") + (f"-{safe_label}" if safe_label else ""))
    os.makedirs(dest, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)

    files: list[str] = []
    for name in sorted(os.listdir(data_dir)):
        src = os.path.join(data_dir, name)
        if os.path.islink(src) or not os.path.isfile(src) or not _wanted_file(name):
            continue
        dst = os.path.join(dest, name)
        if name.endswith(".db"):
            _copy_db(src, dst)
        else:
            shutil.copy2(src, dst)
        files.append(name)
    for name in INCLUDE_DIRS:
        src = os.path.join(data_dir, name)
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.copytree(src, os.path.join(dest, name), symlinks=True, ignore=_skip_special_files)
            files.append(name + "/")

    manifest = {"created_at": time.time(), "label": label, "files": files, **(extra or {})}
    with open(os.path.join(dest, MANIFEST), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    _prune(root, protect)
    logger.info(f"[Snapshot] Saved {len(files)} item(s) to {dest}")
    return dest


def _prune(root: str, protect: str | None = None) -> None:
    keep_name = os.path.basename(os.path.normpath(protect)) if protect else None
    snaps = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and d != keep_name)
    for old in snaps[:-KEEP]:
        shutil.rmtree(os.path.join(root, old), ignore_errors=True)


def list_snapshots(data_dir: str) -> list[dict[str, Any]]:
    root = snapshot_root(data_dir)
    if not os.path.isdir(root):
        return []
    out = []
    for d in sorted(os.listdir(root), reverse=True):
        path = os.path.join(root, d)
        try:
            with open(os.path.join(path, MANIFEST), encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        out.append({"id": d, "path": path, **meta})
    return out


def restore_snapshot(snapshot_dir: str, data_dir: str) -> list[str]:
    """Copies a snapshot back over data_dir. Run only while ZettNAS is stopped."""
    with open(os.path.join(snapshot_dir, MANIFEST), encoding="utf-8") as f:
        files = json.load(f).get("files") or []
    restored = []
    for item in files:
        src = os.path.join(snapshot_dir, item.rstrip("/"))
        dst = os.path.join(data_dir, item.rstrip("/"))
        if item.endswith("/"):
            if os.path.isdir(dst) and not os.path.islink(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=True)
        else:
            for suffix in ("-wal", "-shm"):
                if os.path.exists(dst + suffix):
                    os.remove(dst + suffix)
            tmp = dst + ".restore-tmp"
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)
        restored.append(item)
    logger.warning(f"[Snapshot] Restored {len(restored)} item(s) from {snapshot_dir}")
    return restored
