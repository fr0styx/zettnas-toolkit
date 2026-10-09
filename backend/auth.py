import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import Request

from backend import config
from backend.api_tokens import validate_api_token
from backend.config import SESSION_TTL, SESSIONS_FILE, logger
from backend.errors import error_response
from backend.fsutil import atomic_write_json
from backend.users_db import (
    create_user_session,
    get_user_by_username,
    init_users_db,
    revoke_all_sessions_for_user,
    revoke_user_session,
    validate_scoped_api_token,
    validate_user_session,
)

# Ensure SQLite User DB and migrations are ready
try:
    init_users_db()
except Exception as e:
    logger.warning(f"Could not auto-initialize users DB on auth import: {e}")

SESSIONS: Dict[str, Any] = {}
_sessions_file_mtime_ns = 0
_sessions_lock = threading.RLock()


def _load_sessions():
    """Thread-safe cached session loader for legacy sessions.json fallback."""
    global SESSIONS, _sessions_file_mtime_ns
    with _sessions_lock:
        try:
            if not os.path.exists(SESSIONS_FILE):
                SESSIONS = {}
                _sessions_file_mtime_ns = 0
                return
            mtime = os.stat(SESSIONS_FILE).st_mtime_ns
            if mtime == _sessions_file_mtime_ns and SESSIONS:
                return
            with open(SESSIONS_FILE) as f:
                raw = json.load(f)
            now = time.time()
            SESSIONS = {t: data for t, data in raw.items() if data.get("expires", 0) > now}
            _sessions_file_mtime_ns = mtime
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load sessions.json: {e}")
            SESSIONS = {}
            _sessions_file_mtime_ns = 0


def _save_sessions():
    """Thread-safe session persistence with atomic cache synchronization."""
    global _sessions_file_mtime_ns
    with _sessions_lock:
        try:
            now = time.time()
            valid = {t: data for t, data in SESSIONS.items() if data.get("expires", 0) > now}
            atomic_write_json(SESSIONS_FILE, valid)
            if os.path.exists(SESSIONS_FILE):
                try:
                    _sessions_file_mtime_ns = os.stat(SESSIONS_FILE).st_mtime_ns
                except OSError:
                    pass
        except OSError as e:
            logger.warning(f"Failed to save sessions.json: {e}")


def create_session(username: str, is_remembered: bool = False, ip: str = "", user_agent: str = "") -> str:
    """Create session in SQLite user store and sync to legacy memory map."""
    # Find user in SQLite
    user = get_user_by_username(username)
    if not user:
        user = get_user_by_username("admin")
    user_id = user["id"] if user else "admin-00000000-0000-0000-0000-000000000001"

    token = create_user_session(user_id, username, ip=ip, user_agent=user_agent, is_remembered=is_remembered)

    now = time.time()
    ttl = 30 * 86400 if is_remembered else SESSION_TTL
    with _sessions_lock:
        SESSIONS[token] = {"user": username, "created": now, "expires": now + ttl}
    _save_sessions()
    return token


def revoke_session(token: str) -> None:
    if not token:
        return
    revoke_user_session(token)
    with _sessions_lock:
        target_token = None
        for t in SESSIONS.keys():
            if hmac.compare_digest(token, t):
                target_token = t
                break
        if target_token:
            del SESSIONS[target_token]
            _save_sessions()


def is_internal_token(token: str) -> bool:
    return bool(token) and hmac.compare_digest(token, config.LCD_INTERNAL_TOKEN)


def get_current_session(token: str) -> Optional[Dict[str, Any]]:
    """Retrieve full authenticated session metadata (user_id, username, role_id, scopes)."""
    if not token:
        return None
    if is_internal_token(token):
        return {
            "user_id": "system-internal-0001",
            "username": "system",
            "role_id": "superadmin",
            "scopes": ["*"],
            "is_system": True,
        }
    if token.startswith("zat_"):
        tok = validate_scoped_api_token(token)
        if tok:
            return {
                "user_id": tok["user_id"],
                "username": tok["username"],
                "role_id": tok["role_id"],
                "scopes": tok["scopes"],
                "is_api_token": True,
            }
        if validate_api_token(token):
            return {
                "user_id": "admin-00000000-0000-0000-0000-000000000001",
                "username": config.ZETTNAS_USERNAME or "admin",
                "role_id": "superadmin",
                "scopes": ["*"],
                "is_api_token": True,
            }

    sess = validate_user_session(token)
    if sess:
        return sess

    # Fallback to in-memory legacy session
    with _sessions_lock:
        for t, data in SESSIONS.items():
            if hmac.compare_digest(token, t):
                if data.get("expires", 0) > time.time():
                    return {
                        "user_id": "admin-00000000-0000-0000-0000-000000000001",
                        "username": data.get("user", "admin"),
                        "role_id": "superadmin",
                        "scopes": ["*"],
                    }
    return None


def validate_session(token: str) -> bool:
    """Fast session and API token validation against SQLite store and in-memory caches."""
    if not token:
        return False
    if is_internal_token(token):
        return True

    # 1. Scoped or legacy API token
    if token.startswith("zat_"):
        if validate_scoped_api_token(token):
            return True
        if validate_api_token(token):
            return True
        return False

    # 2. SQLite User session
    sess = validate_user_session(token)
    if sess:
        return True

    # 3. Fallback to in-memory map or sessions.json
    with _sessions_lock:
        session = None
        for t, data in SESSIONS.items():
            if hmac.compare_digest(token, t):
                session = data
                break

        if not session and os.path.exists(SESSIONS_FILE):
            try:
                mtime = os.stat(SESSIONS_FILE).st_mtime_ns
                if mtime != _sessions_file_mtime_ns:
                    _load_sessions()
                    for t, data in SESSIONS.items():
                        if hmac.compare_digest(token, t):
                            session = data
                            break
            except OSError:
                pass

        if not session:
            return False

        if session.get("expires", 0) <= time.time():
            revoke_session(token)
            return False
        return True


def invalidate_all_sessions():
    global SESSIONS
    with _sessions_lock:
        SESSIONS = {}
    _save_sessions()
    try:
        from backend.users_db import USERS_DB_PATH, _SESSION_CACHE, _SESSION_CACHE_LOCK, users_db_session

        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE.clear()

        with users_db_session(USERS_DB_PATH) as conn:
            conn.execute("DELETE FROM sessions")
    except Exception as e:
        logger.warning(f"Could not clear sessions table: {e}")


def extract_token(request: Request) -> str:
    """Extract auth token from Authorization header, HttpOnly cookie, or query param."""
    # 1. Authorization: Bearer <token>
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()

    # 2. HttpOnly Session Cookie: zettnas_session
    cookie_token = request.cookies.get("zettnas_session", "").strip()
    if cookie_token:
        return cookie_token

    # 3. Query string token (fallback for EventSource and docs)
    return request.query_params.get("token", "").strip()


_PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/v1/auth/login",
    "/api/health",
    "/api/v1/health",
    "/api/metrics",
    "/api/v1/metrics",
}
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Reject oversized bodies early (before the route reads them into memory).
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > config.MAX_BODY_BYTES:
        return error_response(413, "Request body too large.")

    is_api = path.startswith("/api/")
    is_docs = path in _DOCS_PATHS
    is_exempt = (
        path in _PUBLIC_API_PATHS
        or path.startswith("/api/wallpapers/download/")
        or path.startswith("/api/v1/wallpapers/download/")
    )

    if is_docs and not config.ENABLE_API_DOCS:
        return error_response(404, "Not found.")

    if (is_api and not is_exempt) or is_docs:
        token = extract_token(request)
        if not token and is_docs:
            ref_qs = parse_qs(urlparse(request.headers.get("referer", "")).query)
            token = (ref_qs.get("token") or [""])[0]
        if not validate_session(token):
            client_host = request.client.host if request.client else "unknown"
            logger.warning(f"Auth failed for client {client_host} accessing {path}")
            return error_response(401, "Unauthorized. Please log in.")

    return await call_next(request)
