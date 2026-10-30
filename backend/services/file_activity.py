"""Who did what to which file (FEAT-12).

The File Explorer and the file API record deletes, renames, moves, copies, restores, uploads,
new folders and archives here, in history.db. Administrators (audit:read) can search it in
Settings → Security; entries older than 90 days are removed. Recording never fails a file
operation: a database error is logged and the operation goes on.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from backend.ignored_errors import ignored

RETENTION_DAYS = 90
MAX_LIMIT = 500
ACTIONS = (
    "delete",  # moved to the Recycle Bin
    "delete_permanent",
    "rename",
    "move",
    "copy",
    "restore",
    "empty_bin",
    "upload",
    "mkdir",
    "archive",
    "extract",
)
_PRUNE_EVERY = 3600.0
_last_prune = [0.0]


def _who(principal: Any) -> tuple[str, str]:
    username = str(getattr(principal, "username", "") or "")
    via = "api token" if getattr(principal, "is_api_token", False) else ""
    return username, via


def _outside_encryption(path: str, target: str, detail: str) -> tuple[str, str, str]:
    """Names inside an encrypted folder stay inside it: the log keeps only the folder (NSEC-3)."""
    from backend.fsutil import ENCRYPTED_ROOT

    def folder(p: str) -> tuple[str, bool]:
        if not p.startswith(ENCRYPTED_ROOT + "/"):
            return p, False
        return "/".join(p.split("/")[:4]), True

    path, hid = folder(path or "")
    target, hid_t = folder(target or "")
    if hid or hid_t:
        detail = "inside an encrypted folder"
    return path, target, detail


def record(action: str, path: str, principal: Any = None, target: str = "", detail: str = "") -> bool:
    """Adds one entry; returns whether it was written."""
    if action not in ACTIONS:
        raise ValueError(f"unknown file action {action!r}")
    from backend.auth import CLIENT_IP_CTX
    from backend.db import db_session

    username, via = _who(principal)
    path, target, detail = _outside_encryption(path, target, detail)
    now = time.time()
    try:
        with db_session() as conn:
            conn.execute(
                "INSERT INTO file_activity (ts, username, ip, action, path, target, detail, via)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now, username, CLIENT_IP_CTX.get()[:64], action, path[:4096], target[:4096], detail[:300], via),
            )
            if now - _last_prune[0] > _PRUNE_EVERY:
                _last_prune[0] = now
                conn.execute("DELETE FROM file_activity WHERE ts < ?", (now - RETENTION_DAYS * 86400,))
    except sqlite3.Error:
        ignored("backend.services.file_activity.record")
        return False
    return True


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(
    q: str = "",
    user: str = "",
    action: str = "",
    days: int = RETENTION_DAYS,
    limit: int = 100,
    before_id: int | None = None,
    hide_under: str = "",
) -> list[dict[str, Any]]:
    """Newest first. `q` matches the path or the new path; `before_id` pages back. With
    `hide_under` (the homes folder), what is inside it shows only whose home it is, and `q`
    doesn't look inside it (NSEC-13)."""
    from backend.db import db_read_session

    where: list[str] = ["ts >= ?"]
    args: list[Any] = [time.time() - max(1, min(int(days), RETENTION_DAYS)) * 86400]
    if q.strip() and hide_under:
        inside = hide_under.rstrip("/") + "/%"
        where.append(
            "((path LIKE ? ESCAPE '\\' AND path NOT LIKE ?) OR (target LIKE ? ESCAPE '\\' AND target NOT LIKE ?))"
        )
        args += [_like(q.strip()), inside, _like(q.strip()), inside]
    elif q.strip():
        where.append("(path LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\')")
        args += [_like(q.strip()), _like(q.strip())]
    if user.strip():
        where.append("username = ?")
        args.append(user.strip().lower())
    if action:
        if action not in ACTIONS:
            raise ValueError(f"unknown file action {action!r}")
        where.append("action = ?")
        args.append(action)
    if before_id is not None:
        where.append("id < ?")
        args.append(int(before_id))
    sql = (
        "SELECT id, ts, username, ip, action, path, target, detail, via FROM file_activity"
        f" WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?"
    )
    args.append(max(1, min(int(limit), MAX_LIMIT)))
    cols = ("id", "ts", "username", "ip", "action", "path", "target", "detail", "via")
    with db_read_session() as conn:
        rows: list[dict[str, Any]] = [dict(zip(cols, row, strict=True)) for row in conn.execute(sql, args).fetchall()]
    if hide_under:
        for r in rows:
            r["path"], r["target"] = mask_home(r["path"], hide_under), mask_home(r["target"] or "", hide_under)
    return rows


def mask_home(path: str, homes: str) -> str:
    """A path inside someone's home folder as "<homes>/<name>/…": whose it is, not what (NSEC-13)."""
    prefix = homes.rstrip("/") + "/"
    if not path.startswith(prefix):
        return path
    owner, _, rest = path[len(prefix) :].partition("/")
    return prefix + owner + ("/…" if rest else "")


def for_user(username: str, limit: int = 5000) -> list[dict[str, Any]]:
    """Their own entries, newest first (export, SEC-32)."""
    from backend.db import db_read_session

    cols = ("ts", "ip", "action", "path", "target", "detail", "via")
    with db_read_session() as conn:
        rows = conn.execute(
            "SELECT ts, ip, action, path, target, detail, via FROM file_activity"
            " WHERE lower(username) = lower(?) ORDER BY id DESC LIMIT ?",
            (username, limit),
        ).fetchall()
    return [dict(zip(cols, r, strict=True)) for r in rows]


def forget_user(username: str, alias: str, home: str = "") -> int:
    """Erase: their entries stay, so the log still adds up, but under a pseudonym and without
    their address; paths in their home folder lose the file names (NSEC-13)."""
    from backend.db import db_session

    if not username:
        return 0
    with db_session() as conn:
        cur = conn.execute(
            "UPDATE file_activity SET username = ?, ip = '' WHERE lower(username) = lower(?)", (alias, username)
        )
        changed = max(0, cur.rowcount or 0)
        prefix = home.rstrip("/") + "/" if home and home not in (".", "/") else ""
        if prefix:
            for sql in (
                "UPDATE file_activity SET path = ? WHERE substr(path, 1, ?) = ?",
                "UPDATE file_activity SET target = ? WHERE substr(target, 1, ?) = ?",
            ):
                conn.execute(sql, (prefix + "…", len(prefix), prefix))
    return changed
