"""One way to open ZettNAS's SQLite databases (ARC-30).

Each database has a profile: the pragmas every connection to it gets, and whether it goes
through db_crypto (the AI databases can be encrypted with the AI data key). The helpers in
users_db, db, ai_conversations_db and rag_engine all open through connect(), so a pragma is
changed in one place and two connections to one file never disagree.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

_COMMON = ("synchronous=NORMAL", "busy_timeout=15000")
PROFILES: dict[str, dict[str, Any]] = {
    # people, sessions, tokens, audit: foreign keys hold the links between them
    "users": {"crypto": False, "pragmas": (*_COMMON, "foreign_keys=ON")},
    # the metrics history: big sequential reads for the charts
    "history": {
        "crypto": False,
        "pragmas": (*_COMMON, "mmap_size=268435456", "cache_size=-64000", "temp_store=MEMORY"),
    },
    # Ask Zetty's conversations (may be encrypted)
    "ai_conversations": {"crypto": True, "wal": True, "pragmas": (*_COMMON, "foreign_keys=ON")},
    # the AI search index (may be encrypted; rag_engine also loads sqlite-vec and caps the WAL)
    "rag_index": {"crypto": True, "wal": True, "pragmas": (*_COMMON, "foreign_keys=ON", "temp_store=MEMORY")},
}


def connect(name: str, path: str, *, readonly: bool = False, row_factory: bool = True, timeout: float = 15.0) -> Any:
    """A connection to database `name` at `path`, with that database's pragmas applied."""
    profile = PROFILES[name]
    if not readonly:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    module: Any = sqlite3
    if profile["crypto"]:
        from backend import db_crypto

        module = db_crypto.sqlite3  # SQLCipher's driver when installed: its own Row and errors
        conn = db_crypto.connect(path, readonly=readonly, timeout=timeout, check_same_thread=False)
    elif readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=timeout, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, timeout=timeout, check_same_thread=False)
    if row_factory:
        conn.row_factory = module.Row
    try:
        if profile.get("wal") and not readonly:
            conn.execute("PRAGMA journal_mode=WAL;")
        for pragma in profile["pragmas"]:
            conn.execute(f"PRAGMA {pragma};")
    except Exception:
        conn.close()
        raise
    return conn
