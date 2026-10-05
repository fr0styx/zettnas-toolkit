import os
import json
import time
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse
from backend.config import logger, SESSIONS_FILE, SESSION_TTL

SESSIONS = {}

def _load_sessions():
    global SESSIONS
    try:
        if os.path.exists(SESSIONS_FILE):
            with open(SESSIONS_FILE, "r") as f:
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
        with open(SESSIONS_FILE, "w") as f:
            json.dump(valid, f)
    except OSError as e:
        logger.warning(f"Failed to save sessions.json: {e}")

def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    SESSIONS[token] = {
        "user": username,
        "created": now,
        "expires": now + SESSION_TTL
    }
    _save_sessions()
    return token

def validate_session(token: str) -> bool:
    if not token or token not in SESSIONS:
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

async def auth_middleware(request: Request, call_next):
    # Allow public static paths, login, and wallpaper downloads without token
    path = request.url.path
    is_api = path.startswith("/api/") or path.startswith("/api/v1/")
    is_exempt = (
        path in ["/api/auth/login", "/api/v1/auth/login"] or
        path.startswith("/api/wallpapers/download/") or
        path.startswith("/api/v1/wallpapers/download/")
    )

    if is_api and not is_exempt:
        client_host = request.client.host if request.client else ""
        if client_host not in ["127.0.0.1", "localhost", "::1"]:
            token = request.headers.get("Authorization", "").replace("Bearer ", "").strip() or request.query_params.get("token", "").strip()
            if not validate_session(token):
                logger.warning(f"Auth failed for client {client_host} accessing {path}")
                return JSONResponse(status_code=401, content={"detail": "Unauthorized. Please log in."})

    return await call_next(request)
