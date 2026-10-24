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

Changing a table (ARCH-7): append a migration function to that database's list in
MIGRATIONS. Never edit or remove one that has shipped. MIGRATIONS[name][i] upgrades
schema v(i+1) to v(i+2); v1 is what the init code creates. Each migration runs in
its own transaction together with the version bump, so a failed one changes nothing.
"""

import logging
import os
import time
from collections.abc import Callable

from backend import config, db_crypto
from backend.db_crypto import DataKeyError, sqlite3

logger = logging.getLogger("ZettNAS")

Migration = Callable[[sqlite3.Connection], None]

# Numbered migrations per database, in order (see the module docstring)
MIGRATIONS: dict[str, list[Migration]] = {
    "users.db": [],
    "history.db": [],
    "ai_conversations.db": [],
    "rag_index.db": [],
}
REBUILDABLE = {"rag_index.db"}


def _versions() -> dict[str, tuple[int, bool]]:
    return {name: (1 + len(steps), name in REBUILDABLE) for name, steps in MIGRATIONS.items()}


# name -> (schema version this code writes, can it be rebuilt from scratch?)
SCHEMA_VERSIONS: dict[str, tuple[int, bool]] = _versions()


class NewerDatabaseError(RuntimeError):
    pass


def _path(name: str, data_dir: str) -> str:
    if name == "users.db":
        return getattr(config, "USERS_DB_PATH", "") or os.path.join(data_dir, name)
    if name == "history.db":
        return getattr(config, "DB_PATH", "") or os.path.join(data_dir, name)
    return os.path.join(data_dir, name)


def read_version(path: str) -> int:
    conn = db_crypto.connect(path, readonly=True, timeout=15.0)
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
        except (sqlite3.Error, DataKeyError) as e:
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


def migrate(name: str, path: str) -> int:
    """Brings one database to the version this code writes; returns that version."""
    steps = MIGRATIONS.get(name, [])
    conn = db_crypto.connect(path, timeout=15.0)
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        if version == 0:  # just created by the init code, which writes v1
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
            version = 1
        for index in range(version - 1, len(steps)):
            target = index + 2
            try:
                conn.execute("BEGIN IMMEDIATE")
                steps[index](conn)
                conn.execute(f"PRAGMA user_version = {target}")
                conn.commit()
            except Exception:
                conn.rollback()
                logger.critical(f"[DB Schema] Migration of {name} to v{target} failed; it stays at v{target - 1}")
                raise
            logger.info(f"[DB Schema] {name} migrated to schema v{target}")
            version = target
        return version
    finally:
        conn.close()


def stamp_versions(data_dir: str = "") -> None:
    """Runs pending migrations and records the schema version in every existing database."""
    base = data_dir or config.DATA_DIR
    for name in SCHEMA_VERSIONS:
        path = _path(name, base)
        if not os.path.exists(path):
            continue
        try:
            migrate(name, path)
        except (sqlite3.Error, DataKeyError) as e:
            logger.warning(f"[DB Schema] Could not migrate {name}: {e}")
