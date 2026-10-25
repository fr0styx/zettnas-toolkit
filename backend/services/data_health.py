"""
Corruption checks and nightly copies of the ZettNAS data folder (REL-2).

At start, before anything opens them, every database in the data folder gets a
`PRAGMA quick_check`. A damaged one is moved aside (name.db.corrupt-<time>) and
replaced by the newest copy from a snapshot that passes the same check; without
one, the app recreates it empty and says so. The AI search index is skipped: it is
large and can be rebuilt.

A daily snapshot (data/backups/daily, the newest seven kept) gives those checks,
and people, something recent to go back to.
"""

import logging
import os
import shutil
import time
from typing import Any

logger = logging.getLogger("ZettNAS")

SKIP_DBS = ("rag_index.db",)
DAILY_SUBDIR = os.path.join("backups", "daily")
DAILY_KEEP = 7
DAILY_EVERY_SECS = 24 * 3600
CHECK_EVERY_SECS = 3600


def _db_ok(path: str) -> bool:
    """True if SQLite reads the file and quick_check finds nothing wrong."""
    from backend import db_crypto

    try:
        if db_crypto.applies_to(path) and db_crypto.is_encrypted(path) and not db_crypto.enabled():
            return True  # no key here to check it with; the app reports the missing key itself
        conn = db_crypto.connect(path, readonly=True)
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
        finally:
            conn.close()
        return bool(row) and str(row[0]).lower() == "ok"
    except Exception:
        logger.warning(f"[DataHealth] {os.path.basename(path)} could not be checked", exc_info=True)
        return False


def _snapshot_dirs(data_dir: str) -> list[str]:
    """Snapshot folders, newest first (pre-update and daily)."""
    from backend.services.data_snapshot import snapshot_root

    roots = [snapshot_root(data_dir), os.path.join(data_dir, DAILY_SUBDIR)]
    dirs = []
    for root in roots:
        if os.path.isdir(root):
            dirs += [os.path.join(root, d) for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    return sorted(dirs, key=lambda d: os.path.basename(d), reverse=True)


def _restore_db(data_dir: str, name: str) -> str | None:
    """Puts the newest good copy of `name` back; returns the snapshot it came from."""
    target = os.path.join(data_dir, name)
    for snap in _snapshot_dirs(data_dir):
        copy = os.path.join(snap, name)
        if os.path.isfile(copy) and _db_ok(copy):
            tmp = target + ".restore-tmp"
            shutil.copy2(copy, tmp)
            os.replace(tmp, target)
            return snap
    return None


def check_and_repair(data_dir: str) -> dict[str, Any]:
    """Checks every database in the data folder; moves damaged ones aside and restores the newest
    good copy. Run at start, before the databases are opened."""
    result: dict[str, Any] = {"checked": [], "repaired": {}, "lost": []}
    try:
        names = sorted(n for n in os.listdir(data_dir) if n.endswith(".db") and n not in SKIP_DBS)
    except OSError:
        return result
    for name in names:
        path = os.path.join(data_dir, name)
        result["checked"].append(name)
        if _db_ok(path):
            continue
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(path + suffix):
                os.replace(path + suffix, f"{path}{suffix}.corrupt-{stamp}")
        source = _restore_db(data_dir, name)
        if source:
            result["repaired"][name] = os.path.basename(source)
            logger.critical(f"[DataHealth] {name} was damaged; restored the copy from {os.path.basename(source)}")
        else:
            result["lost"].append(name)
            logger.critical(f"[DataHealth] {name} was damaged and no good copy exists; it starts empty")
    if result["repaired"] or result["lost"]:
        _record_event(result)
    return result


def _record_event(result: dict[str, Any]) -> None:
    try:
        from backend.state import add_event

        parts = [f"{n} restored from the copy of {s}" for n, s in result["repaired"].items()]
        parts += [f"{n} could not be restored and started empty" for n in result["lost"]]
        add_event(
            "error",
            "Damaged data repaired",
            "ZettNAS found damaged files at start: " + "; ".join(parts) + ". The damaged files were kept beside them.",
            details=result,
        )
    except Exception:
        logger.debug("[DataHealth] could not record the repair event", exc_info=True)


def take_daily_snapshot_if_due(data_dir: str, now: float | None = None) -> str | None:
    """One snapshot a day in data/backups/daily, the newest seven kept."""
    from backend.services.data_snapshot import take_snapshot

    now = now or time.time()
    root = os.path.join(data_dir, DAILY_SUBDIR)
    newest = 0.0
    if os.path.isdir(root):
        for d in os.listdir(root):
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, d)))
            except OSError:
                continue
    if now - newest < DAILY_EVERY_SECS:
        return None
    return take_snapshot(data_dir, label="daily", root=root, keep=DAILY_KEEP)


def data_guard_daemon(data_dir: str | None = None, sleep=time.sleep) -> None:
    """Supervised: takes the daily snapshot when it is due."""
    from backend import config

    folder = data_dir or config.DATA_DIR
    while True:
        try:
            take_daily_snapshot_if_due(folder)
        except Exception:
            logger.warning("[DataHealth] daily snapshot failed", exc_info=True)
        sleep(CHECK_EVERY_SECS)
