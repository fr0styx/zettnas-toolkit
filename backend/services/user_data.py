"""Everything ZettNAS keeps about one person, to hand over or to forget (B8).

Export (one JSON file): the account (no password or secrets), its API tokens (names, scopes,
dates; never the token), every chat with its messages, the log of their questions to Zetty
(when and how, not what), the files search learned from their own folder, and their entries in
the security log.

Erase, each part on its own:
- chats: every conversation and message;
- ai_log: their rows in Zetty's request log;
- index: what search learned from their own folder, which is then not learned again
  (rag forget_folder). Their files themselves are not touched.

Deleting an account erases all three. The security log and the file activity log keep their
entries, as the server's record of what happened, but under a pseudonym and without the
person's address (file_activity: file names in their home folder go too, NSEC-13).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from backend.config import logger

FORMAT = 1
PARTS = ("chats", "ai_log", "index", "security_log", "file_activity")
MAX_INDEX_FILES = 20000
MAX_EVENTS = 5000

PROFILE_FIELDS = (
    "id",
    "username",
    "display_name",
    "email",
    "role_id",
    "status",
    "created_at",
    "last_login_at",
    "home_directory",
    "storage_quota_bytes",
)


def _conv_user(user: dict[str, Any]) -> str:
    # chats are stored under the principal's user id, lower case (api/media.py)
    return str(user.get("id") or user.get("username") or "").strip().lower()


def _profile(user: dict[str, Any]) -> dict[str, Any]:
    out = {k: user.get(k) for k in PROFILE_FIELDS if k in user}
    try:
        out["preferences"] = json.loads(user.get("preferences_json") or "{}")
    except ValueError:
        out["preferences"] = {}
    return out


def _chats(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.services.ai_conversations_db import get_conversation_with_messages, list_conversations

    uid = _conv_user(user)
    out = []
    for c in list_conversations(uid, include_archived=True, limit=100000):
        full = get_conversation_with_messages(c["id"], uid)
        if full:
            out.append(full)
    return out


def _home(user: dict[str, Any]) -> str:
    from backend.services.user_spaces import home_of

    return os.path.normpath(home_of(str(user.get("username") or "")))


def _index_files(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.services.rag_engine import get_rag_engine

    home = _home(user)
    prefix = home.rstrip("/") + "/"
    eng = get_rag_engine()
    conn = eng._get_conn(readonly=True)
    try:
        rows = conn.execute(
            "SELECT canonical_path, file_name, indexed_at FROM indexed_files "
            "WHERE canonical_path = ? OR substr(canonical_path, 1, ?) = ? ORDER BY canonical_path LIMIT ?",
            (home, len(prefix), prefix, MAX_INDEX_FILES),
        ).fetchall()
    finally:
        conn.close()
    return [{"path": r[0], "name": r[1], "indexed_at": r[2]} for r in rows]


def _security_events(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.users_db import users_db_session

    with users_db_session(readonly=True) as conn:
        rows = conn.execute(
            "SELECT event_type, status, actor_ip, details_json, timestamp FROM security_audit_log "
            "WHERE actor_id = ? ORDER BY timestamp DESC LIMIT ?",
            (user.get("id"), MAX_EVENTS),
        ).fetchall()
    out = []
    for r in rows:
        try:
            details = json.loads(r[3] or "{}")
        except ValueError:
            details = {}
        out.append({"event": r[0], "status": r[1], "ip": r[2], "details": details, "ts": r[4]})
    return out


def _part(name: str, fn, user: dict[str, Any]) -> Any:
    try:
        return fn(user)
    except Exception:
        logger.warning("[UserData] Could not export %s for %s", name, user.get("username"), exc_info=True)
        return {"error": f"Could not read {name}; the rest of the export is complete."}


def _calendar(user: dict[str, Any]) -> dict[str, Any]:
    from backend import config
    from backend.fsutil import read_json

    store = read_json(os.path.join(config.DATA_DIR, "calendar_data.json"), {}) or {}

    def mine(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in i.items() if k != "owner"} for i in items if i.get("owner") == user.get("id")]

    feeds = mine(store.get("feeds", []))
    ids = {f.get("id") for f in feeds}
    return {
        "notes": mine(store.get("notes", [])),
        "feeds": feeds,
        "feed_events": [e for e in store.get("feed_events", []) if e.get("feed_id") in ids],
    }


def _share_links(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend import config
    from backend.fsutil import read_json

    links = read_json(os.path.join(config.DATA_DIR, "shared_links.json"), {}) or {}
    secret = ("password_hash", "token", "password")
    return [
        {k: v for k, v in link.items() if k not in secret}
        for link in (links.values() if isinstance(links, dict) else [])
        if isinstance(link, dict) and link.get("created_by") == user.get("username")
    ]


def _favorites(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend import config
    from backend.fsutil import read_json

    data = read_json(os.path.join(config.DATA_DIR, "fm_favorites.json"), {}) or {}
    return list(data.get(str(user.get("username") or "").lower(), [])) if isinstance(data, dict) else []


def _devices(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.services import web_push

    return [
        {k: v for k, v in s.items() if k not in ("keys", "endpoint")}
        for s in web_push.subscriptions(str(user.get("username") or ""))
    ]


def _alert_route(user: dict[str, Any]) -> dict[str, Any]:
    from backend.services.notifications import get_routes

    return dict(get_routes().get(str(user.get("username") or "")) or {})


def _file_activity(user: dict[str, Any]) -> list[dict[str, Any]]:
    from backend.services import file_activity

    return file_activity.for_user(str(user.get("username") or ""))


def _immich(user: dict[str, Any]) -> dict[str, Any]:
    from backend.services import immich_photos

    c = immich_photos._cfg()
    name = str(user.get("username") or "")
    return {
        "connected": bool((c.get("keys") or {}).get(name)),
        "phone_backup_done": name in (c.get("phone_done") or []),
    }


# Every store that holds something of one person's, and the export key it goes under. A test
# checks this against the stores (SEC-32), so a new per-person store needs a line here.
STORES = (
    "account",
    "api_tokens",
    "chats",
    "ai_requests",
    "search_index",
    "security_events",
    "calendar",
    "share_links",
    "favorites",
    "phone_devices",
    "alert_route",
    "immich",
    "file_activity",
)


def export_user(user: dict[str, Any]) -> dict[str, Any]:
    """One person's data as a JSON-ready dict."""
    from backend.services import ai_access
    from backend.users_db import list_user_api_tokens

    return {
        "format": FORMAT,
        "exported_at": int(time.time()),
        "account": _profile(user),
        "api_tokens": _part("api_tokens", lambda u: list_user_api_tokens(u["id"]), user),
        "chats": _part("chats", _chats, user),
        "ai_requests": _part("ai_requests", lambda u: ai_access.recent(500, u.get("username")), user),
        "search_index": {
            "folder": _part("folder", _home, user),
            "files": _part("files", _index_files, user),
        },
        "security_events": _part("security_events", _security_events, user),
        "calendar": _part("calendar", _calendar, user),
        "share_links": _part("share_links", _share_links, user),
        "favorites": _part("favorites", _favorites, user),
        "phone_devices": _part("phone_devices", _devices, user),
        "alert_route": _part("alert_route", _alert_route, user),
        "immich": _part("immich", _immich, user),
        "file_activity": _part("file_activity", _file_activity, user),
    }


def erase_user_data(user: dict[str, Any], parts: tuple[str, ...] = PARTS) -> dict[str, Any]:
    """Forgets the chosen parts; returns what was removed per part (or the error)."""
    done: dict[str, Any] = {}
    for part in parts:
        if part not in PARTS:
            raise ValueError(f"Unknown part '{part}'; choose from {', '.join(PARTS)}")
    if "chats" in parts:
        try:
            from backend.services.ai_conversations_db import clear_all_conversations

            done["chats"] = clear_all_conversations(_conv_user(user))
        except Exception:
            logger.warning("[UserData] Could not erase chats of %s", user.get("username"), exc_info=True)
            done["chats"] = {"error": "Could not erase the chats."}
    if "ai_log" in parts:
        try:
            from backend.services import ai_access

            done["ai_log"] = ai_access.forget_user(str(user.get("username") or ""))
        except Exception:
            logger.warning("[UserData] Could not erase the AI log of %s", user.get("username"), exc_info=True)
            done["ai_log"] = {"error": "Could not erase the request log."}
    if "index" in parts:
        try:
            from backend.services.rag_engine import get_rag_engine

            home = _home(user)
            done["index"] = get_rag_engine().forget_folder(home) if home and home not in (".", "/") else {}
        except Exception:
            logger.warning("[UserData] Could not erase the index entries of %s", user.get("username"), exc_info=True)
            done["index"] = {"error": "Could not erase what search learned."}
    if "security_log" in parts:
        try:
            from backend.users_db import pseudonymise_security_log

            done["security_log"] = pseudonymise_security_log(str(user.get("id") or ""))
        except Exception:
            logger.warning(
                "[UserData] Could not pseudonymise the security log of %s", user.get("username"), exc_info=True
            )
            done["security_log"] = {"error": "Could not remove their name from the security log."}
    if "file_activity" in parts:
        try:
            import hashlib
            import sqlite3

            from backend.services import file_activity

            alias = "erased-" + hashlib.sha256(str(user.get("id") or "").encode()).hexdigest()[:10]
            done["file_activity"] = file_activity.forget_user(str(user.get("username") or ""), alias, _home(user))
        except (sqlite3.Error, OSError, ValueError):
            logger.warning("[UserData] Could not erase the file activity of %s", user.get("username"), exc_info=True)
            done["file_activity"] = {"error": "Could not remove their name from the file activity log."}
    return done
