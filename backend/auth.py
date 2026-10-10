import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, HTTPException, Request

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
    if token.startswith("zst_"):
        from backend.api.auth import validate_and_consume_stream_ticket

        tok = validate_and_consume_stream_ticket(token)
        if tok:
            return tok

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

    # 0. Single-use stream ticket
    if token.startswith("zst_"):
        from backend.api.auth import _STREAM_TICKETS, _STREAM_TICKETS_LOCK

        with _STREAM_TICKETS_LOCK:
            return token in _STREAM_TICKETS

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
    "/api/auth/mfa/challenge",
    "/api/v1/auth/mfa/challenge",
    "/api/auth/users-list",
    "/api/v1/auth/users-list",
    "/api/health",
    "/api/v1/health",
    "/api/metrics",
    "/api/v1/metrics",
}
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def is_ip_in_trusted_proxies(client_ip: str, trusted_list: Optional[List[str]] = None) -> bool:
    """Check if client IP matches configured trusted proxies or CIDR subnets."""
    if not client_ip or client_ip == "unknown":
        return False
    import ipaddress

    proxies = trusted_list if trusted_list is not None else getattr(config, "TRUSTED_PROXIES", ["127.0.0.1", "::1"])
    if client_ip in proxies:
        return True

    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        return False

    for trusted in proxies:
        try:
            if "/" in trusted:
                net = ipaddress.ip_network(trusted, strict=False)
                if ip_obj in net:
                    return True
            else:
                if ip_obj == ipaddress.ip_address(trusted):
                    return True
        except ValueError:
            continue
    return False


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
        client_host = request.client.host if request.client else "unknown"

        # Reverse Proxy Header SSO (Authelia, Authentik, Traefik, Cloudflare Access)
        if getattr(config, "ENABLE_PROXY_SSO", False) and is_ip_in_trusted_proxies(client_host):
            proxy_user = (
                request.headers.get("Remote-User")
                or request.headers.get("X-Forwarded-User")
                or request.headers.get("X-Forwarded-Preferred-Username")
            )
            if proxy_user:
                proxy_user = proxy_user.strip()
                user = get_user_by_username(proxy_user)
                if not user:
                    try:
                        from backend.users_db import create_user

                        email = request.headers.get("Remote-Email") or request.headers.get("X-Forwarded-Email") or ""
                        display_name = request.headers.get("Remote-Name") or proxy_user
                        user = create_user(
                            username=proxy_user,
                            display_name=display_name,
                            password=secrets.token_urlsafe(32),
                            email=email,
                            role_id="share_user",
                            idp_type="proxy_sso",
                            idp_sub=proxy_user,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to auto-provision proxy user '{proxy_user}': {e}")
                        user = get_user_by_username(proxy_user)

                if user and user.get("status") == "active":
                    sso_sess = {
                        "user_id": user["id"],
                        "username": user["username"],
                        "role_id": user["role_id"],
                        "scopes": user.get("scopes", []),
                        "is_proxy_sso": True,
                    }
                    request.state.session = sso_sess
                    request.state.user = sso_sess
                    request.state.token = f"sso_{user['username']}"
                    return await call_next(request)

        token = extract_token(request)
        if not token and is_docs:
            ref_qs = parse_qs(urlparse(request.headers.get("referer", "")).query)
            token = (ref_qs.get("token") or [""])[0]
        if not validate_session(token):
            if path in ("/api/stats", "/api/stats/stream", "/api/metrics"):
                logger.debug(f"Auth failed for client {client_host} accessing polling route {path}")
            else:
                logger.warning(f"Auth failed for client {client_host} accessing {path}")
            return error_response(401, "Unauthorized. Please log in.")

        sess = get_current_session(token)
        if sess:
            request.state.session = sess
            request.state.user = sess
            request.state.token = token

    return await call_next(request)


# ==============================================================================
# RBAC Scope Evaluation & FastAPI Dependencies
# ==============================================================================


def has_scope(user_scopes: List[str], required_scope: str) -> bool:
    """Evaluates whether granted user_scopes satisfy the required_scope.

    Supports:
    - Global wildcard: '*' matches all scopes
    - Global read wildcard: '*:read' matches any ':read' or ':view' scope
    - Domain wildcard: 'storage:*' matches 'storage:read', 'storage:write', 'storage:admin'
    - Permission hierarchy: ':admin' or ':manage' matches ':write' and ':read'; ':write' matches ':read'
    """
    if not user_scopes:
        return False
    if "*" in user_scopes:
        return True
    if required_scope in user_scopes:
        return True

    # Global read wildcard (*:read)
    if "*:read" in user_scopes and (required_scope.endswith(":read") or required_scope.endswith(":view")):
        return True

    # Check domain-level hierarchy (e.g. storage:* matches storage:read)
    if ":" in required_scope:
        domain, action = required_scope.split(":", 1)
        if f"{domain}:*" in user_scopes:
            return True
        # Hierarchy: admin / manage > write > read / view
        if action in ("read", "view"):
            if any(f"{domain}:{act}" in user_scopes for act in ("write", "admin", "manage", "power")):
                return True
        elif action == "write":
            if any(f"{domain}:{act}" in user_scopes for act in ("admin", "manage")):
                return True

    return False


class AuthenticatedPrincipal:
    """Represents an active, authenticated user or service token principal with scopes."""

    def __init__(self, data: Dict[str, Any]):
        self.user_id: str = data.get("user_id", "")
        self.username: str = data.get("username", "")
        self.role_id: str = data.get("role_id", "share_user")
        self.scopes: List[str] = data.get("scopes", [])
        self.is_api_token: bool = data.get("is_api_token", False)
        self.is_system: bool = data.get("is_system", False)
        self.raw_data: Dict[str, Any] = data

    def has_scope(self, scope: str) -> bool:
        return has_scope(self.scopes, scope)

    def has_any_scope(self, *scopes: str) -> bool:
        return any(self.has_scope(s) for s in scopes)

    def has_all_scopes(self, *scopes: str) -> bool:
        return all(self.has_scope(s) for s in scopes)

    def __repr__(self) -> str:
        return f"<AuthenticatedPrincipal username={self.username} role={self.role_id} scopes={self.scopes}>"


def get_current_principal(request: Request) -> AuthenticatedPrincipal:
    """FastAPI dependency that returns the AuthenticatedPrincipal from request context."""
    sess = getattr(request.state, "session", None)
    if not sess:
        token = extract_token(request)
        if not token:
            raise HTTPException(status_code=401, detail="Authentication credentials required.")
        sess = get_current_session(token)
        if not sess:
            raise HTTPException(status_code=401, detail="Invalid or expired session.")

    return AuthenticatedPrincipal(sess)


def require_scope(*required_scopes: str):
    """FastAPI dependency factory enforcing that the authenticated principal possesses

    at least one of the specified scopes (with wildcard and role resolution).
    """

    def _dependency(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
        if not required_scopes:
            return principal

        satisfied = any(principal.has_scope(scope) for scope in required_scopes)
        if not satisfied:
            required_str = ", ".join(required_scopes)
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied. Required scope: '{required_str}'. Current role: '{principal.role_id}'.",
            )
        return principal

    return _dependency
