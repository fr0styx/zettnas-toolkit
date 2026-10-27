"""The Recycle Bin of each storage root: .RecycleBin/files with a .trashinfo per item in
.RecycleBin/info, the layout the File Explorer lists and restores from.

Deleting in the File Explorer puts items here, and so does replacing an item during a copy, a move
or a snapshot restore (REL-14): an overwrite never destroys the old version.
"""

import os
import shutil
import time
from datetime import UTC, datetime

from backend import config
from backend.config import logger
from backend.fsutil import root_for

BIN = ".RecycleBin"


def bin_for(path: str) -> str | None:
    """The Recycle Bin for `path`, or None outside the storage roots or inside a bin already."""
    real = os.path.realpath(path)
    root = root_for(real, config.ALLOWED_BROWSE_ROOTS)
    if not root or f"/{BIN}/" in real[len(root) :] + "/":
        return None
    return os.path.join(root, BIN)


def _slot(files_dir: str, base_name: str, now: float) -> str:
    ts = int(now)
    name, n = f"{ts}_{base_name}", 1
    while os.path.lexists(os.path.join(files_dir, name)):  # two items of one name in one second
        n += 1
        name = f"{ts}-{n}_{base_name}"
    return name


def move_to_bin(
    path: str, recycle_dir: str | None = None, original: str | None = None, rename_only: bool = False
) -> str | None:
    """Moves `path` into a Recycle Bin and returns its id there. None when there is no bin for it,
    or (rename_only) when it is on another filesystem than the bin and would have to be copied."""
    recycle_dir = recycle_dir or bin_for(path)
    if not recycle_dir:
        return None
    files_dir, info_dir = os.path.join(recycle_dir, "files"), os.path.join(recycle_dir, "info")
    os.makedirs(files_dir, exist_ok=True)
    os.makedirs(info_dir, exist_ok=True)
    name = _slot(files_dir, os.path.basename(path.rstrip("/")), time.time())
    info = os.path.join(info_dir, f"{name}.trashinfo")
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(info, "w", encoding="utf-8") as f:
            f.write(f"[Trash Info]\nPath={original or path}\nDeletionDate={stamp}\n")
    except OSError as err:
        logger.warning(f"[Recycle Bin] Could not write {info}: {err}")
    dest = os.path.join(files_dir, name)
    try:
        if rename_only:
            os.rename(path, dest)
        else:
            shutil.move(path, dest)
    except OSError:
        if os.path.exists(info):
            os.unlink(info)
        if rename_only and os.path.lexists(path):
            logger.info(f"[Recycle Bin] {path} is on another filesystem than {recycle_dir}")
            return None
        raise
    return name
