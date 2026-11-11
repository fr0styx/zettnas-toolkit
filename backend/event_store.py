"""The event log's store (SET-13).

The event log was the 100 newest entries in events.json, and an entry had no identity: nothing
could link to it or mark it read for one person, and a busy day pushed a failed backup out of
the list. Each entry now has an id, a kind (the name of its text: "ups_power_back") and a link
(the place that deals with it), and is kept for 90 days in history.db, next to File activity.

The list in memory and events.json stay as they were: the live stream reads the list, and an
older build still finds its file. Writing never fails the caller: an entry that cannot be stored
stays in memory and in the file, and the error is counted (backend.ignored_errors).
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from backend.ignored_errors import ignored

RETENTION_DAYS = 90
MAX_LIMIT = 500
_PRUNE_EVERY = 3600.0
_state: dict[str, Any] = {"table_in": "", "pruned": 0.0}

# The place that deals with an event, by the start of its kind. The first match wins. A place is a
# name the interface can open (frontend/src/router.js); "" means the Event Log itself.
LINKS: tuple[tuple[str, str], ...] = (
    ("ai_", "ai"),
    ("alert_unsent", "alerts"),
    ("api_access_", "settings"),
    ("app_", "apps"),
    ("prune_", "apps"),
    ("backup_", "backup"),
    ("bond_", "network"),
    ("bridge_", "network"),
    ("vlan_", "network"),
    ("net_", "network"),
    ("ip_blocked", "network"),
    ("webdav_", "network"),
    ("button_", "cards"),
    ("card_", "cards"),
    ("copy_", "cards"),
    ("usb_import", "cards"),
    ("data_", "storage"),
    ("pool.", "storage"),
    ("unraid_error", "storage"),
    ("default_login", "settings"),
    ("two_factor_off", "users"),
    ("security", "settings"),
    ("drive_", "drives"),
    ("smart_", "drives"),
    ("sched_", "drives"),
    ("fan_", "hardware"),
    ("cpu_hot", "hardware"),
    ("fm_", "files"),
    ("guard_", "settings"),
    ("malware_", "settings"),
    ("iso_", "vms"),
    ("vm_", "vms"),
    ("settings_", "settings"),
    ("update_", "settings"),
    ("ups_", "power"),
)
_COLUMNS = "id, ts, last_ts, level, kind, link, title, message, details, count"


def kind_of(details: Any) -> str:
    """The name of an entry's text: "ups_power_back" for ev.ups_power_back.title, "pool.fixed" for
    alert.pool.fixed.title. "" for an entry written without a text key."""
    if not isinstance(details, dict):
        return ""
    if isinstance(details.get("kind"), str) and details["kind"]:
        return details["kind"]
    parts = str(details.get("title_key") or details.get("msg_key") or "").split(".")
    return ".".join(parts[1:-1]) if len(parts) >= 3 and parts[0] in ("ev", "alert") else ""


def link_of(kind: str, details: Any = None) -> str:
    """The place that deals with an entry; an entry may name its own (details["link"])."""
    if isinstance(details, dict) and isinstance(details.get("link"), str) and details["link"]:
        return details["link"]
    for prefix, place in LINKS:
        if kind.startswith(prefix):
            return place
    return ""


def _table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            ts INTEGER NOT NULL,
            last_ts INTEGER NOT NULL,
            level TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT '',
            link TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            details TEXT NOT NULL DEFAULT '',
            count INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_last_ts ON events(last_ts)")


@contextmanager
def _open() -> Iterator[sqlite3.Connection]:
    """A session on history.db with the events table in place (made once per database file)."""
    from backend import db

    with db.db_session() as conn:
        if _state["table_in"] != db.DB_PATH:
            _table(conn)
            _state["table_in"] = db.DB_PATH
        yield conn


def _row(e: dict[str, Any]) -> tuple:
    ts = int(e.get("ts") or 0)
    details = e.get("details")
    return (
        int(e["id"]),
        ts,
        int(e.get("last_ts") or ts),
        str(e.get("level") or "info"),
        str(e.get("kind") or ""),
        str(e.get("link") or ""),
        str(e.get("title") or ""),
        str(e.get("message") or ""),
        json.dumps(details, ensure_ascii=False, default=str) if details is not None else "",
        int(e.get("count") or 1),
    )


def _entry(row: tuple) -> dict[str, Any]:
    """A stored row as the entry the stream sends: what is empty is left out."""
    eid, ts, last_ts, level, kind, link, title, message, details, count = row
    e: dict[str, Any] = {"id": eid, "ts": ts, "level": level, "title": title, "message": message}
    if kind:
        e["kind"] = kind
    if link:
        e["link"] = link
    if details:
        try:
            e["details"] = json.loads(details)
        except ValueError:
            ignored("backend.event_store._entry")
    if count > 1:
        e["count"] = count
        e["last_ts"] = last_ts
    return e


def save(entries: list[dict[str, Any]]) -> bool:
    """Writes new entries and changed counts, by id. False when the store could not be written."""
    if not entries:
        return True
    now = time.time()
    try:
        with _open() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO events (" + _COLUMNS + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [_row(e) for e in entries],
            )
            if now - _state["pruned"] > _PRUNE_EVERY:
                _state["pruned"] = now
                conn.execute("DELETE FROM events WHERE last_ts < ?", (int(now - RETENTION_DAYS * 86400),))
    except (sqlite3.Error, OSError):
        ignored("backend.event_store.save")
        return False
    return True


def newest(limit: int = 100, before_id: int | None = None, level: str = "") -> list[dict[str, Any]] | None:
    """Entries, the most recently seen first. None when the store cannot be read."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    where, args = [], []
    if before_id is not None:
        where.append("id < ?")
        args.append(int(before_id))
    if level:
        where.append("level = ?")
        args.append(level)
    sql = "SELECT " + _COLUMNS + " FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY last_ts DESC, id DESC LIMIT ?"
    try:
        with _open() as conn:
            return [_entry(r) for r in conn.execute(sql, [*args, limit]).fetchall()]
    except (sqlite3.Error, OSError):
        ignored("backend.event_store.newest")
        return None


def last_id() -> int:
    """The highest id in the store; 0 when it is empty or cannot be read."""
    try:
        with _open() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])
    except (sqlite3.Error, OSError):
        ignored("backend.event_store.last_id")
        return 0


def carry_over(old: list[dict[str, Any]], first_id: int = 1) -> list[dict[str, Any]]:
    """Entries from events.json that have no id yet (written before the store, or by an older
    build since) get one, oldest first, with their kind and link. Returns them newest first."""
    out: list[dict[str, Any]] = []
    plain = [e for e in old if isinstance(e, dict) and "id" not in e and e.get("title") is not None]
    for n, e in enumerate(sorted(plain, key=lambda x: x.get("ts") or 0)):
        kind = kind_of(e.get("details"))
        link = link_of(kind, e.get("details"))
        entry = {**e, "id": first_id + n, "ts": int(e.get("ts") or 0)}
        if kind:
            entry["kind"] = kind
        if link:
            entry["link"] = link
        out.append(entry)
    save(out)
    return out[::-1]


def clear() -> bool:
    try:
        with _open() as conn:
            conn.execute("DELETE FROM events")
    except (sqlite3.Error, OSError):
        ignored("backend.event_store.clear")
        return False
    return True
