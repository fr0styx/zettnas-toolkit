"""
Schema versions for ZettNAS SQLite databases (OPS-03).

Each database records its schema version in `PRAGMA user_version`. On start:

- a database written by a NEWER ZettNAS (higher version than this code knows)
  stops startup, because older code could corrupt it. The fix is to run the
  newer version again, or restore the pre-update snapshot in
  data/backups/pre-update/ (the updater does this automatically on rollback);
- the rebuildable search index is moved aside instead, and rebuilt;
- after the init code has created or upgraded the tables, each database is
  stamped with the version this code writes.

When a release changes a table, bump its number here and add the upgrade step
to that database's init code.
"""

import logging
import os
import sqlite3
import time

from backend import config

logger = logging.getLogger("ZettNAS")

# name -> (schema version this code writes, can it be rebuilt from scratch?)
SCHEMA_VERSIONS: dict[str, tuple[int, bool]] = {
    "users.db": (1, False),
    "history.db": (1, False),
    "ai_conversations.db": (1, False),
    "rag_index.db": (1, True),
}


class NewerDatabaseError(RuntimeError):
    pass


def _path(name: str, data_dir: str) -> str:
    if name == "users.db":
        return getattr(config, "USERS_DB_PATH", "") or os.path.join(data_dir, name)
    if name == "history.db":
        return getattr(config, "DB_PATH", "") or os.path.join(data_dir, name)
    return os.path.join(data_dir, name)


def read_version(path: str) -> int:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15.0)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def check_versions(data_dir: str = "") -> list[str]:
    """Raises NewerDatabaseError for a newer non-rebuildable database. Returns moved-aside paths."""
    base = data_dir or config.DATA_DIR
    moved: list[str] = []
    for name, (known, rebuildable) in SCHEMA_VERSIONS.items():
        path = _path(name, base)
        if not os.path.exists(path):
            continue
        try:
            found = read_version(path)
        except sqlite3.Error as e:
            logger.warning(f"[DB Schema] Could not read the schema version of {name}: {e}")
            continue
        if found <= known:
            continue
        if rebuildable:
            aside = f"{path}.newer-v{found}-{int(time.time())}"
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(path + suffix):
                    os.replace(path + suffix, aside + suffix)
            logger.warning(
                f"[DB Schema] {name} is schema v{found} (this version knows v{known}); moved aside to rebuild"
            )
            moved.append(aside)
            continue
        raise NewerDatabaseError(
            f"{name} was written by a newer ZettNAS (schema v{found}, this version supports v{known}). "
            "Start the newer version again, or restore the matching snapshot from data/backups/pre-update/."
        )
    return moved


def stamp_versions(data_dir: str = "") -> None:
    """Records the current schema version in every database that is older."""
    base = data_dir or config.DATA_DIR
    for name, (known, _rebuildable) in SCHEMA_VERSIONS.items():
        path = _path(name, base)
        if not os.path.exists(path):
            continue
        try:
            conn = sqlite3.connect(path, timeout=15.0)
            try:
                if int(conn.execute("PRAGMA user_version").fetchone()[0]) < known:
                    conn.execute(f"PRAGMA user_version = {int(known)}")
                    conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.warning(f"[DB Schema] Could not stamp {name}: {e}")
