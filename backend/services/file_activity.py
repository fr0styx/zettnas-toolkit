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


def record(action: str, path: str, principal: Any = None, target: str = "", detail: str = "") -> bool:
    """Adds one entry; returns whether it was written."""
    if action not in ACTIONS:
        raise ValueError(f"unknown file action {action!r}")
    from backend.auth import CLIENT_IP_CTX
    from backend.db import db_session

    username, via = _who(principal)
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
) -> list[dict[str, Any]]:
    """Newest first. `q` matches the path or the new path; `before_id` pages back."""
    from backend.db import db_read_session

    where: list[str] = ["ts >= ?"]
    args: list[Any] = [time.time() - max(1, min(int(days), RETENTION_DAYS)) * 86400]
    if q.strip():
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
        return [dict(zip(cols, row, strict=True)) for row in conn.execute(sql, args).fetchall()]
