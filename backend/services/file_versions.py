"""Previous versions of a file (missing feature 7): the copies kept in snapshots.

Two sources, whichever the file lives on:
  - ZFS: every dataset shows its snapshots under <mountpoint>/.zfs/snapshot/<name>/ (TrueNAS,
    Unraid ZFS pools, any Linux ZFS), found by walking up from the file;
  - btrfs: the share snapshots ZettNAS takes itself (snapshot_service, "<share>@auto-...").

Only versions that differ from the file today (and from each other) are listed."""

import os
import shutil
import tempfile
import time
from typing import Any

from backend.config import logger
from backend.fsutil import resolve_within

MAX_VERSIONS = 200
_MAX_WALK = 32


def _zfs_candidates(real: str) -> list[dict[str, Any]]:
    d = os.path.dirname(real)
    for _ in range(_MAX_WALK):
        snapdir = os.path.join(d, ".zfs", "snapshot")
        if os.path.isdir(snapdir):
            rel = os.path.relpath(real, d)
            out = []
            try:
                names = os.listdir(snapdir)
            except OSError:
                return []
            for name in names:
                root = os.path.join(snapdir, name)
                try:
                    created = os.stat(root).st_mtime  # a snapshot's root carries its creation time
                except OSError:
                    continue
                out.append({"id": f"zfs:{name}", "label": name, "root": root, "rel": rel, "created": created})
            return out
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return []


def _btrfs_candidates(real: str) -> list[dict[str, Any]]:
    try:
        from backend.services import snapshot_service as snaps

        pal = snaps._pal()
        pool_id = snaps._default_pool_id(pal)
        listed = pal.list_snapshots(pool_id)
    except Exception:
        logger.debug("file_versions: no btrfs snapshots", exc_info=True)
        return []
    out = []
    for snap in listed or []:
        name, path = snap.get("name") or "", snap.get("path") or ""
        if not name or not path:
            continue
        try:
            live = os.path.realpath(snaps._live_root(name, pal, pool_id))
        except Exception:  # noqa: BLE001 - a snapshot whose share is gone has no versions here
            continue
        if not real.startswith(live.rstrip("/") + "/"):
            continue
        out.append(
            {
                "id": f"btrfs:{name}",
                "label": name,
                "root": os.path.realpath(path),
                "rel": os.path.relpath(real, live),
                "created": float(snap.get("created_at") or 0),
            }
        )
    return out


def _candidates(real: str) -> list[dict[str, Any]]:
    found = []
    for c in _zfs_candidates(real) + _btrfs_candidates(real):
        target = resolve_within(os.path.join(c["root"], c["rel"]), c["root"])
        if target is None or not os.path.isfile(target) or os.path.islink(target):
            continue
        st = os.stat(target)
        found.append({**c, "path": target, "size": st.st_size, "mtime": st.st_mtime})
    found.sort(key=lambda c: c["created"], reverse=True)
    return found


def list_versions(path: str) -> list[dict[str, Any]]:
    """The file's earlier versions, newest first: id, label, created, size, mtime."""
    real = os.path.realpath(path)
    try:
        cur = os.stat(real)
        current = (cur.st_size, int(cur.st_mtime))
    except OSError:
        current = None  # deleted today: every kept copy is a version
    out: list[dict[str, Any]] = []
    seen = {current} if current else set()
    for c in _candidates(real):
        key = (c["size"], int(c["mtime"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({k: c[k] for k in ("id", "label", "created", "size", "mtime")})
        if len(out) >= MAX_VERSIONS:
            break
    return out


def version_path(path: str, version_id: str) -> str:
    """Where one version's bytes are (looked up again, never taken from the request)."""
    real = os.path.realpath(path)
    for c in _candidates(real):
        if c["id"] == version_id:
            return c["path"]
    raise FileNotFoundError("That version isn't there any more.")


def restore_version(path: str, version_id: str, overwrite: bool = False) -> str:
    """Copies a version back: beside the file as "<name> (version YYYY-MM-DD HHMM)", or over it."""
    src = version_path(path, version_id)
    real = os.path.realpath(path)
    folder = os.path.dirname(real)
    if overwrite:
        fd, tmp = tempfile.mkstemp(prefix=".zettnas-restore-", dir=folder)
        os.close(fd)
        try:
            shutil.copy2(src, tmp)
            os.replace(tmp, real)  # one step: the file is never half-written
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return real
    stem, ext = os.path.splitext(os.path.basename(real))
    stamp = time.strftime("%Y-%m-%d %H%M", time.localtime(os.stat(src).st_mtime))
    dest = os.path.join(folder, f"{stem} (version {stamp}){ext}")
    n = 2
    while os.path.lexists(dest):
        dest = os.path.join(folder, f"{stem} (version {stamp}) {n}{ext}")
        n += 1
    shutil.copy2(src, dest)
    return dest
