"""The Recycle Bins: one per share (<share>/.RecycleBin) and one per storage root for items at
the top. Each holds files/ with a .trashinfo per item in info/, the layout the File Explorer lists
and restores from; Samba's recycle module puts what is deleted over SMB into files/ too (REL-15).

Deleting in the File Explorer puts items here, and so does replacing an item during a copy, a move
or a snapshot restore (REL-14): an overwrite never destroys the old version.

Auto-empty (REL-15, D9): an item goes 30 days after it was deleted, and the oldest go first when a
bin holds more than 10% of its disk. What was already in a bin when this arrived counts its 30
days from then (the grace start), and the size cap removes none of it before those 30 days end.
Bins are emptied only when they are used anyway (a delete into them, the Recycle Bin opened, a
restore), never by a sweep of their own, so no sleeping disk is woken for it. A small index in
the data folder keeps each bin's size for the Overview.
"""

import os
import shutil
import threading
import time
from datetime import UTC, datetime
from typing import Any

from backend import config
from backend.config import logger
from backend.fsutil import atomic_write_json, read_json, root_for

BIN = ".RecycleBin"
KEEP_DAYS = 30
MAX_SHARE_OF_DISK = 0.10
CHECK_EVERY_SECS = 3600
_LOCK = threading.Lock()


def _index_file() -> str:
    return os.path.join(config.DATA_DIR, "recycle_bins.json")


def _index() -> dict[str, Any]:
    data = read_json(_index_file(), {}) or {}
    return data if isinstance(data, dict) else {}


def _save_index(data: dict[str, Any]) -> None:
    try:
        atomic_write_json(_index_file(), data)
    except OSError as err:
        logger.warning(f"[Recycle Bin] Could not save the index: {err}")


def grace_start(now: float | None = None) -> float:
    """When auto-empty arrived here; items deleted before it count their days from then (D9)."""
    with _LOCK:
        data = _index()
        if not data.get("grace_start"):
            data["grace_start"] = now or time.time()
            _save_index(data)
        return float(data["grace_start"])


def bin_for(path: str) -> str | None:
    """The Recycle Bin for `path`: its share's, or the root's for an item at the top. None
    outside the storage roots or inside a bin already."""
    real = os.path.realpath(path)
    from backend.services import encrypted_index

    if real.startswith(encrypted_index.ROOT + "/"):
        return encrypted_index.bin_for(real)  # inside the folder, so it stays encrypted (FEAT-13)
    root = root_for(real, config.ALLOWED_BROWSE_ROOTS)
    rel = real[len(root) :].strip("/") if root else ""
    if not root or not rel or BIN in rel.split("/"):
        return None
    parts = rel.split("/")
    return os.path.join(root, parts[0], BIN) if len(parts) > 1 else os.path.join(root, BIN)


def all_bins() -> list[str]:
    """Every bin that exists: each root's, each share's, and those the index knows."""
    found: list[str] = []
    for root in config.ALLOWED_BROWSE_ROOTS:
        candidates = [os.path.join(root, BIN)]
        try:
            with os.scandir(root) as it:
                candidates += [
                    os.path.join(e.path, BIN)
                    for e in it
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")
                ]
        except OSError:
            logger.debug(f"[Recycle Bin] {root} unreadable", exc_info=True)
        found += [c for c in candidates if os.path.isdir(c)]
    for known in _index().get("bins") or {}:
        if known not in found and os.path.isdir(known):
            found.append(known)
    return found


def _slot(files_dir: str, base_name: str, now: float) -> str:
    ts = int(now)
    name, n = f"{ts}_{base_name}", 1
    while os.path.lexists(os.path.join(files_dir, name)):  # two items of one name in one second
        n += 1
        name = f"{ts}-{n}_{base_name}"
    return name


def _size(path: str) -> int:
    if not os.path.isdir(path) or os.path.islink(path):
        try:
            return os.lstat(path).st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(dirpath, f)).st_size
            except OSError:
                continue
    return total


def _deleted_at(recycle_dir: str, name: str, path: str) -> float:
    info = os.path.join(recycle_dir, "info", f"{name}.trashinfo")
    if os.path.exists(info):
        try:
            with open(info, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DeletionDate="):
                        stamp = line.split("=", 1)[1].strip().replace("Z", "+00:00")
                        return datetime.fromisoformat(stamp).timestamp()
        except (OSError, ValueError):
            logger.debug(f"[Recycle Bin] {info} unreadable", exc_info=True)
    head = name.split("_", 1)[0].split("-", 1)[0]
    if head.isdigit() and len(head) >= 9:
        return float(head)
    try:
        return os.lstat(path).st_mtime  # Samba's recycle sets it to the deletion time
    except OSError:
        return time.time()


def items(recycle_dir: str) -> list[dict[str, Any]]:
    """What a bin holds: name, path, when it was deleted, size."""
    out = []
    for folder in (os.path.join(recycle_dir, "files"), recycle_dir):
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            if e.name.startswith(".") or (folder == recycle_dir and e.name in ("files", "info")):
                continue
            out.append(
                {
                    "name": e.name,
                    "path": e.path,
                    "deleted_at": _deleted_at(recycle_dir, e.name, e.path),
                    "size": _size(e.path),
                }
            )
    return out


def _remove(recycle_dir: str, item: dict[str, Any]) -> None:
    path = item["path"]
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)
    info = os.path.join(recycle_dir, "info", f"{item['name']}.trashinfo")
    if os.path.exists(info):
        os.unlink(info)


def _disk_bytes(recycle_dir: str) -> int:
    try:
        st = os.statvfs(recycle_dir)
        return st.f_blocks * st.f_frsize
    except OSError:
        return 0


def auto_empty(recycle_dir: str, now: float | None = None, force: bool = False) -> int:
    """Removes what this bin should no longer keep; returns how many items went. Checked at most
    once an hour per bin, and only because the bin is in use anyway."""
    now = now or time.time()
    start = grace_start(now)
    with _LOCK:
        data = _index()
        bins = data.setdefault("bins", {})
        entry = bins.get(recycle_dir) or {}
        if not force and now - float(entry.get("checked") or 0) < CHECK_EVERY_SECS:
            return 0
    keep = KEEP_DAYS * 86400
    held = items(recycle_dir)
    for i in held:
        i["counts_from"] = max(i["deleted_at"], start)
    removed = 0
    for i in sorted(held, key=lambda x: x["counts_from"]):
        if now - i["counts_from"] > keep:
            try:
                _remove(recycle_dir, i)
                removed += 1
                i["gone"] = True
            except OSError as err:
                logger.warning(f"[Recycle Bin] Could not remove {i['path']}: {err}")
    left = [i for i in held if not i.get("gone")]
    total, cap = sum(i["size"] for i in left), int(_disk_bytes(recycle_dir) * MAX_SHARE_OF_DISK)
    in_grace = now - start <= keep
    for i in sorted(left, key=lambda x: x["deleted_at"]):
        if not cap or total <= cap:
            break
        if in_grace and i["deleted_at"] < start:
            continue  # D9: what was there at the upgrade stays its 30 days
        try:
            _remove(recycle_dir, i)
            removed += 1
            total -= i["size"]
        except OSError as err:
            logger.warning(f"[Recycle Bin] Could not remove {i['path']}: {err}")
    with _LOCK:
        data = _index()
        data.setdefault("bins", {})[recycle_dir] = {
            "bytes": total,
            "items": len([i for i in left if os.path.lexists(i["path"])]),
            "checked": now,
        }
        _save_index(data)
    if removed:
        logger.info(f"[Recycle Bin] Emptied {removed} item(s) from {recycle_dir}")
    return removed


def item_id(recycle_dir: str, name: str) -> str:
    """How the File Explorer names an item: "<share>::<name>" in a share's bin, the name in a
    root's bin (as before per-share bins)."""
    parent = os.path.dirname(recycle_dir)
    if parent in [os.path.realpath(r) for r in config.ALLOWED_BROWSE_ROOTS] or parent in config.ALLOWED_BROWSE_ROOTS:
        return name
    return f"{os.path.basename(parent)}::{name}"


def locate(ident: str) -> tuple[str, str] | None:
    """The bin and the entry name of an item id; None when no bin holds it."""
    share, _, name = ident.rpartition("::")
    if not name or "/" in name or name in (".", ".."):
        return None
    for b in all_bins():
        if share and os.path.basename(os.path.dirname(b)) != share:
            continue
        if not share and item_id(b, name) != name:
            continue
        if os.path.lexists(os.path.join(b, "files", name)) or os.path.lexists(os.path.join(b, name)):
            return b, name
    return None


def original_path(recycle_dir: str, name: str) -> str:
    info = os.path.join(recycle_dir, "info", f"{name}.trashinfo")
    try:
        with open(info, encoding="utf-8") as f:
            for line in f:
                if line.startswith("Path="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def total_bytes() -> int:
    """What every bin held when it was last used (from the index: no disk is read)."""
    return sum(int(b.get("bytes") or 0) for b in (_index().get("bins") or {}).values())


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
    try:
        auto_empty(recycle_dir)
    except Exception:
        logger.debug("[Recycle Bin] auto-empty skipped", exc_info=True)
    return name
