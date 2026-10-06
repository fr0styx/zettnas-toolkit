import hmac
import json
import os
import secrets
import time

from fastapi import Request

from backend import config
from backend.config import SESSION_TTL, SESSIONS_FILE, logger
from backend.errors import error_response
from backend.fsutil import atomic_write_json

SESSIONS = {}


def _load_sessions():
    global SESSIONS
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE) as f:
                raw = json.load(f)
                now = time.time()
                SESSIONS = {t: data for t, data in raw.items() if data.get("expires", 0) > now}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load sessions.json: {e}")
        SESSIONS = {}


def _save_sessions():
    try:
        now = time.time()
        valid = {t: data for t, data in SESSIONS.items() if data.get("expires", 0) > now}
        atomic_write_json(SESSIONS_FILE, valid)
    except OSError as e:
        logger.warning(f"Failed to save sessions.json: {e}")


def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    SESSIONS[token] = {"user": username, "created": now, "expires": now + SESSION_TTL}
    _save_sessions()
    return token


def revoke_session(token: str) -> None:
    if token and SESSIONS.pop(token, None) is not None:
        _save_sessions()


def is_internal_token(token: str) -> bool:
    return bool(token) and hmac.compare_digest(token, config.LCD_INTERNAL_TOKEN)


def validate_session(token: str) -> bool:
    if not token:
        return False
    if is_internal_token(token):
        return True

    # Check if it's a persistent API token
    if token.startswith("zat_"):
        try:
            from backend.api_tokens import validate_api_token

            if validate_api_token(token):
                return True
        except ImportError:
            pass

    if token not in SESSIONS:
        return False
    session = SESSIONS[token]
    if session.get("expires", 0) <= time.time():
        del SESSIONS[token]
        _save_sessions()
        return False
    return True


def invalidate_all_sessions():
    global SESSIONS
    SESSIONS = {}
    _save_sessions()


def extract_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()
    # Query-string token is still accepted for EventSource (SSE) and /docs,
    # which cannot send custom headers.
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
            # Swagger UI fetches /openapi.json without our token; inherit it from /docs?token=...
            from urllib.parse import parse_qs, urlparse

            ref_qs = parse_qs(urlparse(request.headers.get("referer", "")).query)
            token = (ref_qs.get("token") or [""])[0]
        if not validate_session(token):
            client_host = request.client.host if request.client else "unknown"
            logger.warning(f"Auth failed for client {client_host} accessing {path}")
            return error_response(401, "Unauthorized. Please log in.")

    return await call_next(request)
