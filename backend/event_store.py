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
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from backend.config import logger

RETENTION_DAYS = 90
MAX_LIMIT = 500
_PRUNE_EVERY = 3600.0
_state: dict[str, Any] = {"table_in": "", "pruned": 0.0, "said": 0.0}
_SAY_EVERY = 3600.0


def _failed(what: str) -> None:
    """A store that cannot be read or written is said, once an hour and not for every entry: the
    entries are still in memory and in events.json."""
    now = time.time()
    if now - _state.get("said", 0.0) >= _SAY_EVERY:
        _state["said"] = now
        logger.warning("[Events] The event store could not be %s; the log goes on in memory", what, exc_info=True)


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


@contextmanager
def _open() -> Iterator[sqlite3.Connection]:
    """A session on history.db with the events table in place (made once per database file)."""
    from backend import db

    with db.db_session() as conn:
        if _state["table_in"] != db.DB_PATH:
            db.create_events_table(conn)  # the table is defined with history.db's others (ARC-24)
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
            e["details"] = {"unreadable": True}  # the row's details were damaged; the entry itself is shown
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
        _failed("written")
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
        _failed("read")
        return None


def last_id() -> int:
    """The highest id in the store; 0 when it is empty or cannot be read."""
    try:
        with _open() as conn:
            return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0])
    except (sqlite3.Error, OSError):
        _failed("read")
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
        _failed("written")
        return False
    return True


# ---- one person's entries: handed over with "export my data", renamed when the account is erased


def _word(username: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w.@-])" + re.escape(username) + r"(?![\w@-])", re.IGNORECASE)


def _param_names(value: Any, username: str) -> bool:
    if isinstance(value, str):
        return value.lower() == username.lower()
    if isinstance(value, dict):
        return any(_param_names(v, username) for v in value.values())
    if isinstance(value, list):
        return any(_param_names(v, username) for v in value)
    return False


def names(entry: dict[str, Any], username: str) -> bool:
    """Whether an entry is about this person: one of its values is their name, or its text has
    the name as a word. A name shorter than four letters counts only as a value ("al" is in
    "alert")."""
    if not username:
        return False
    details = entry.get("details")
    if isinstance(details, dict) and _param_names(details.get("params"), username):
        return True
    if len(username) < 4:
        return False
    word = _word(username)
    return bool(word.search(str(entry.get("title") or "")) or word.search(str(entry.get("message") or "")))


def _renamed(value: Any, username: str, alias: str) -> Any:
    if isinstance(value, str):
        return alias if value.lower() == username.lower() else value
    if isinstance(value, dict):
        return {k: _renamed(v, username, alias) for k, v in value.items()}
    if isinstance(value, list):
        return [_renamed(v, username, alias) for v in value]
    return value


def scrub(entry: dict[str, Any], username: str, alias: str) -> dict[str, Any]:
    """The entry with the person's name replaced by a pseudonym; the entry itself stays, as the
    server's record of what happened."""
    if not names(entry, username):
        return entry
    word = _word(username)
    out = {
        **entry,
        "title": word.sub(alias, str(entry.get("title") or "")),
        "message": word.sub(alias, str(entry.get("message") or "")),
    }
    if isinstance(entry.get("details"), dict):
        out["details"] = {**entry["details"], "params": _renamed(entry["details"].get("params"), username, alias)}
    return out


def _like(username: str) -> str:
    return "%" + username.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _mentioning(conn: sqlite3.Connection, username: str, limit: int) -> list[dict[str, Any]]:
    like = _like(username)
    rows = conn.execute(
        "SELECT " + _COLUMNS + " FROM events WHERE title LIKE ? ESCAPE '\\' OR message LIKE ? ESCAPE '\\'"
        " OR details LIKE ? ESCAPE '\\' ORDER BY last_ts DESC, id DESC LIMIT ?",
        (like, like, like, limit),
    ).fetchall()
    return [e for e in (_entry(r) for r in rows) if names(e, username)]


def for_user(username: str, limit: int = 5000) -> list[dict[str, Any]]:
    """The entries that are about one person, the most recent first (export)."""
    if not username:
        return []
    try:
        with _open() as conn:
            return _mentioning(conn, username, limit)
    except (sqlite3.Error, OSError):
        _failed("read")
        return []


def forget_user(username: str, alias: str) -> int:
    """Erase: the person's name becomes a pseudonym in every entry about them. Returns how many
    entries changed; raises sqlite3.Error or OSError when the store cannot be written."""
    if not username:
        return 0
    with _open() as conn:
        found = _mentioning(conn, username, MAX_LIMIT * 20)
        conn.executemany(
            "INSERT OR REPLACE INTO events (" + _COLUMNS + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [_row(scrub(e, username, alias)) for e in found],
        )
    return len(found)
