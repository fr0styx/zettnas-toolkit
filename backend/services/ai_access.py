"""Who may ask Zetty, and a log of who did (B8: AI access per role).

Each role is on or off for the assistant (chat and its file tools). Kids and guests are off
until an administrator turns them on; every other role is on. The superadmin is always on, so
nobody can lock the household out of its own assistant.

Every chat request is logged: when, who, their role, the model, whether web search was allowed
and how it ended. The question and the answer are not: what someone asked stays in their own
chat history, which only they can read. Rows older than LOG_DAYS are pruned.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

from fastapi import Depends

from backend.auth import AuthenticatedPrincipal, get_current_principal
from backend.config import logger
from backend.errors import ShownServerError

OFF_BY_DEFAULT = ("kid", "guest")
ALWAYS_ON = ("superadmin",)
LOG_DAYS = 90
OUTCOMES = ("answered", "streamed", "failed", "refused")


def role_access(cfg: dict[str, Any] | None = None) -> dict[str, bool]:
    """The saved switches (role id -> on), over the defaults for the roles that start off."""
    if cfg is None:
        from backend.services.rag_engine import get_rag_engine

        cfg = get_rag_engine().get_config()
    raw = cfg.get("ai_role_access")
    saved: dict[str, Any] = raw if isinstance(raw, dict) else {}
    out = {r: False for r in OFF_BY_DEFAULT}
    out.update({str(k): bool(v) for k, v in saved.items()})
    for r in ALWAYS_ON:
        out[r] = True
    return out


def clean_switches(value: Any) -> dict[str, bool]:
    """What may be saved: role ids to on/off; the superadmin cannot be switched off."""
    if not isinstance(value, dict):
        raise ValueError("ai_role_access must map role ids to true or false")
    out = {}
    for k, v in value.items():
        key = str(k).strip()
        if not key or len(key) > 64 or not isinstance(v, bool):
            raise ValueError("ai_role_access must map role ids to true or false")
        if key not in ALWAYS_ON:
            out[key] = v
    return out


def allowed(principal: Any, cfg: dict[str, Any] | None = None) -> bool:
    role = str(getattr(principal, "role_id", "") or "")
    if role in ALWAYS_ON:
        return True
    return role_access(cfg).get(role, True)


def require_ai_access(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
    """FastAPI dependency for the assistant's endpoints."""
    if not allowed(principal):
        log_request(principal, "chat", "", False, "refused")
        raise ShownServerError(
            "Zetty is turned off for your account. An administrator can turn it on in AI settings.",
            status_code=403,
            error="ai_off_for_role",
        )
    return principal


# --- the request log (history.db) -------------------------------------------------------------
def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS ai_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            kind TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            web INTEGER NOT NULL DEFAULT 0,
            outcome TEXT NOT NULL,
            ms INTEGER NOT NULL DEFAULT 0
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_requests_ts ON ai_requests(ts DESC)")


_PRUNED = {"at": 0}


def log_request(
    principal: Any, kind: str, model: str, web: bool, outcome: str, ms: int = 0, now: float | None = None
) -> None:
    """One row per request; never the text of the question or the answer."""
    from backend.db import history_session

    ts = int(now or time.time())
    try:
        with history_session() as conn:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO ai_requests (ts, username, role, kind, model, web, outcome, ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    str(getattr(principal, "username", "") or "")[:64],
                    str(getattr(principal, "role_id", "") or "")[:64],
                    kind[:16],
                    str(model or "")[:128],
                    1 if web else 0,
                    outcome if outcome in OUTCOMES else "failed",
                    max(0, int(ms)),
                ),
            )
            if ts - _PRUNED["at"] >= 3600:
                conn.execute("DELETE FROM ai_requests WHERE ts < ?", (ts - LOG_DAYS * 86400,))
                _PRUNED["at"] = ts
    except sqlite3.Error:
        logger.warning("[AI] Could not log an assistant request", exc_info=True)


def recent(limit: int = 100, username: str | None = None) -> list[dict[str, Any]]:
    from backend.db import history_session

    limit = max(1, min(500, int(limit)))
    try:
        with history_session() as conn:
            _ensure_table(conn)
            cols = "ts, username, role, kind, model, web, outcome, ms"
            if username:
                cur = conn.execute(
                    f"SELECT {cols} FROM ai_requests WHERE username = ? COLLATE NOCASE ORDER BY ts DESC, id DESC LIMIT ?",
                    (username, limit),
                )
            else:
                cur = conn.execute(f"SELECT {cols} FROM ai_requests ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, tuple(r), strict=True)) for r in cur.fetchall()]
            return [r | {"web": bool(r["web"])} for r in rows]
    except sqlite3.Error:
        logger.warning("[AI] Could not read the assistant request log", exc_info=True)
        return []


def roles_with_access() -> list[dict[str, Any]]:
    """Every role with its switch, for AI settings: {id, name, description, on, locked}."""
    from backend.users_db import users_db_session

    with users_db_session(readonly=True) as conn:
        rows = conn.execute("SELECT id, name, description FROM roles ORDER BY is_system DESC, name").fetchall()
    access = role_access()
    return [
        {
            "id": r[0],
            "name": r[1],
            "description": r[2] or "",
            "on": access.get(r[0], True),
            "locked": r[0] in ALWAYS_ON,
        }
        for r in rows
    ]


def forget_user(username: str) -> int:
    """Deletes someone's rows from the request log (user_data.erase_user_data); returns how many."""
    from backend.db import history_session

    if not username:
        return 0
    with history_session() as conn:
        _ensure_table(conn)
        cur = conn.execute("DELETE FROM ai_requests WHERE username = ? COLLATE NOCASE", (username,))
        return max(0, cur.rowcount or 0)
