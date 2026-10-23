import contextvars
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from fastapi import Depends, HTTPException, Request

from backend import config
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


def purge_legacy_session_files() -> None:
    """Deletes the pre-SQLite sessions.json and api_tokens.json stores and their backups.

    Sessions now live only in the users DB. The old file held raw tokens and was
    honoured as a superadmin fallback (SEC-01), so it is removed at startup.
    """
    base = getattr(config, "SESSIONS_FILE", SESSIONS_FILE)
    # The pre-SQLite API token file granted superadmin to any token in it; scoped
    # tokens live in the users DB now.
    tokens_file = os.path.join(os.path.dirname(base), "api_tokens.json")
    for path in (base, base + ".bak", base + ".tmp", tokens_file, tokens_file + ".tmp"):
        try:
            if os.path.lexists(path):
                os.remove(path)
                logger.warning(f"[Auth] Removed legacy session store {os.path.basename(path)}")
        except OSError as e:
            logger.warning(f"[Auth] Could not remove legacy session store {path}: {e}")


def create_session(username: str, is_remembered: bool = False, ip: str = "", user_agent: str = "") -> str:
    """Create a session for an existing user in the SQLite user store."""
    user = get_user_by_username(username)
    if not user:
        # Never fall back to another account (previously: admin).
        raise ValueError(f"Cannot create a session for unknown user '{username}'.")
    return create_user_session(user["id"], user["username"], ip=ip, user_agent=user_agent, is_remembered=is_remembered)


def revoke_session(token: str) -> None:
    if not token:
        return
    revoke_user_session(token)


def is_internal_token(token: str) -> bool:
    return bool(token) and hmac.compare_digest(token, config.LCD_INTERNAL_TOKEN)


def get_current_session(token: str) -> dict[str, Any] | None:
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

    if token.startswith("zct_"):
        # VM console tickets open that VM's console WebSocket only (vms._validate_console_ticket).
        return None

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

    # Only the users DB decides: a revoked, expired or disabled user's session is gone.
    return validate_user_session(token)


def validate_session(token: str) -> bool:
    """Fast session and API token validation against SQLite store and in-memory caches."""
    if not token:
        return False
    if is_internal_token(token):
        return True

    # 0. Single-use stream or VM console ticket
    if token.startswith("zst_"):
        from backend.api.auth import _STREAM_TICKETS, _STREAM_TICKETS_LOCK

        with _STREAM_TICKETS_LOCK:
            return token in _STREAM_TICKETS

    if token.startswith("zct_"):
        return False  # console WebSocket only

    # 1. Scoped API token (users DB only)
    if token.startswith("zat_"):
        return bool(validate_scoped_api_token(token))

    # 2. SQLite user session (the only session store)
    return bool(validate_user_session(token))


def invalidate_all_sessions():
    purge_legacy_session_files()
    try:
        from backend.users_db import _SESSION_CACHE, _SESSION_CACHE_LOCK, USERS_DB_PATH, users_db_session

        with _SESSION_CACHE_LOCK:
            _SESSION_CACHE.clear()

        with users_db_session(USERS_DB_PATH) as conn:
            conn.execute("DELETE FROM sessions")
    except Exception as e:
        logger.warning(f"Could not clear sessions table: {e}")


def query_credential_allowed(value: str) -> str:
    """A credential in a URL is accepted only if it is short-lived or internal (SEC-16).

    URLs end up in logs, browser history and Referer headers, so long-lived session
    and API tokens are never read from them: only single-use stream tickets (zst_),
    VM console tickets and the LCD renderer's internal token.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("zst_") or is_internal_token(value):
        return value
    try:
        from backend.api.vms import _CONSOLE_TICKETS

        if value in _CONSOLE_TICKETS:
            return value
    except Exception:
        logger.debug("backend.auth.query_credential_allowed: ignored error", exc_info=True)
    return ""


def extract_token(request: Request) -> str:
    """Auth token from the Authorization header, the HttpOnly session cookie, or a URL ticket."""
    # 1. Authorization: Bearer <token> (API clients, the LCD renderer)
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return header[7:].strip()

    # 2. HttpOnly session cookie set at login (the web UI)
    cookie_token = request.cookies.get("zettnas_session", "").strip()
    if cookie_token:
        return cookie_token

    # 3. Single-use tickets / internal token only
    return query_credential_allowed(
        request.query_params.get("ticket", "")
        or request.query_params.get("token", "")
        or request.query_params.get("lcd_token", "")
    )


def client_ip(request: Request) -> str:
    """Address of the real client (SEC-20).

    X-Forwarded-For is only read when the connection comes from a trusted proxy, and
    then from the right: the first address that is not itself a trusted proxy. The
    leftmost entry is whatever the client wrote and can't be trusted.
    """
    peer = request.client.host if request.client else "unknown"
    if not is_ip_in_trusted_proxies(peer):
        return peer
    hops = [h.strip() for h in (request.headers.get("x-forwarded-for") or "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not is_ip_in_trusted_proxies(hop):
            return hop
    return hops[0] if hops else peer


def request_is_https(request: Request) -> bool:
    """True for HTTPS, trusting X-Forwarded-Proto only from configured reverse proxies (SEC-17)."""
    if request.url.scheme == "https":
        return True
    client = request.client.host if request.client else ""
    return request.headers.get("x-forwarded-proto", "").lower() == "https" and is_ip_in_trusted_proxies(client)


def _allowed_origins(conn: Any) -> set[str]:
    """This server's own host[:port] plus configured trusted origins (HTTP request or WebSocket)."""
    host = (conn.headers.get("host") or "").lower()
    allowed = {host} | {o.lower().rstrip("/") for o in getattr(config, "CSRF_TRUSTED_ORIGINS", []) or []}
    # Behind a reverse proxy that rewrites Host, trust X-Forwarded-Host from that proxy only.
    client = getattr(getattr(conn, "client", None), "host", "")
    client = client if isinstance(client, str) else ""
    fwd_host = (conn.headers.get("x-forwarded-host") or "").split(",")[0].strip().lower()
    if fwd_host and client and is_ip_in_trusted_proxies(client):
        allowed.add(fwd_host)
    allowed.discard("")
    return allowed


def _origin_in(value: str, allowed: set[str]) -> bool:
    """Full match on host:port (or scheme://host:port), never on the hostname alone."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return bool(parsed.netloc) and (
        parsed.netloc.lower() in allowed or f"{parsed.scheme}://{parsed.netloc}".lower() in allowed
    )


def _origin_matches_host(request: Request) -> bool:
    """CSRF check for cookie-authenticated writes: Origin (or Referer) must be this server."""
    allowed = _allowed_origins(request)
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if value:
            return _origin_in(value, allowed)
    return False


_PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/v1/auth/login",
    "/api/auth/mfa/challenge",
    "/api/v1/auth/mfa/challenge",
    "/api/auth/users-list",
    "/api/v1/auth/users-list",
    "/api/health",
    "/api/v1/health",
    "/api/auth/oidc/config",
    "/api/auth/oidc/login",
    "/api/auth/oidc/callback",
    "/api/csp-report",
    "/api/remotes/oauth/mobile-page",
    "/api/remotes/oauth/mobile-exchange",
    "/redfish/v1",
    "/redfish/v1/",
}
_DOCS_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}


def is_ip_in_trusted_proxies(client_ip: str, trusted_list: list[str] | None = None) -> bool:
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


# What a session that must change its password may still reach (SEC-23).
_PASSWORD_CHANGE_ALLOWED = {
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/auth/ticket"),
    ("GET", "/api/security"),
    ("POST", "/api/security"),
    ("GET", "/api/stats"),
    ("GET", "/api/stats/stream"),
}


def password_change_pending(sess: dict[str, Any]) -> bool:
    if not sess or sess.get("is_system") or sess.get("is_proxy_sso"):
        return False
    if sess.get("must_change_password"):
        return True
    return sess.get("role_id") == "superadmin" and config.is_using_default_password()


def _allowed_while_password_change_pending(method: str, path: str, sess: dict[str, Any]) -> bool:
    norm = path.replace("/api/v1/", "/api/").rstrip("/") or "/"
    if (method, norm) in _PASSWORD_CHANGE_ALLOWED or method == "OPTIONS":
        return True
    return method == "POST" and norm == f"/api/users/{sess.get('user_id')}/password"


_WEBDAV_WRITE_METHODS = {"PUT", "DELETE", "MOVE", "COPY", "MKCOL", "PROPPATCH"}
_FS_READONLY_POSTS = ("/api/fs/conflict-check", "/api/fs/checksum", "/api/fs/folder-size")
CLIENT_IP_CTX: contextvars.ContextVar[str] = contextvars.ContextVar("zettnas_client_ip", default="")


def _is_file_write(path: str, method: str) -> bool:
    """Requests that change files: refused while the ransomware guard has frozen writes (M4)."""
    norm = path.replace("/api/v1/", "/api/")
    if norm.startswith("/webdav"):
        return method in _WEBDAV_WRITE_METHODS
    if norm.startswith("/api/fs/") and method in ("POST", "PUT", "DELETE", "PATCH"):
        return not norm.startswith(_FS_READONLY_POSTS) and "/share-links" not in norm
    return False


async def auth_middleware(request: Request, call_next):
    path = request.url.path

    # Blocked addresses (M5) and the ransomware write freeze (M4) come first
    ip = client_ip(request)
    CLIENT_IP_CTX.set(ip)
    from backend.services import ip_block

    if ip_block.is_blocked(ip):
        return error_response(403, "This address is blocked. An admin can unblock it under Security.")
    if _is_file_write(path, request.method):
        from backend.services.ransomware_guard import get_guard

        if get_guard().frozen:
            return error_response(
                423, "Writes are frozen by the ransomware guard. An admin can lift the freeze under Security."
            )

    # Reject oversized bodies early (before the route reads them into memory).
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit():
        cl_val = int(content_length)
        norm_path = path.replace("/api/v1/", "/api/")
        streaming_endpoints = (
            "/api/fs/upload",
            "/api/vms/isos/upload",
            "/api/system/restore",
            "/api/backup/upload",
        )
        limit = (
            getattr(config, "MAX_UPLOAD_BYTES", 64 * 1024 * 1024 * 1024)
            if any(norm_path.startswith(prefix) for prefix in streaming_endpoints)
            else config.MAX_BODY_BYTES
        )
        if cl_val > limit:
            return error_response(413, "Request body too large.")

    is_api = path.startswith("/api/") or path.startswith("/redfish")
    is_docs = path in _DOCS_PATHS
    is_exempt = (
        path in _PUBLIC_API_PATHS
        or path.startswith("/api/wallpapers/download/")
        # Public share links authenticate with their own token (+ password) (SEC-21)
        or path.startswith(("/api/fs/shared/", "/api/shared/", "/api/v1/fs/shared/", "/api/v1/shared/"))
        or path.startswith("/api/v1/wallpapers/download/")
        or (path.startswith("/api/vms/") and (path.endswith("/console/ws") or path.endswith("/serial/ws")))
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

        sess = get_current_session(token)
        if not sess:
            if path in ("/api/stats", "/api/stats/stream", "/api/metrics"):
                logger.debug(f"Auth failed for client {client_host} accessing polling route {path}")
            else:
                logger.warning(f"Auth failed for client {client_host} accessing {path}")
            return error_response(401, "Unauthorized. Please log in.")

        if (
            getattr(config, "ENFORCE_PASSWORD_CHANGE", True)
            and is_api
            and password_change_pending(sess)
            and not _allowed_while_password_change_pending(request.method, path, sess)
        ):
            return error_response(403, "Change your password before continuing.", error="password_change_required")

        # CSRF (SEC-17): a write that authenticates only with the browser's cookie must
        # come from this server's own pages. Bearer-token clients are not affected.
        if (
            request.method in ("POST", "PUT", "PATCH", "DELETE")
            and not request.headers.get("Authorization", "").startswith("Bearer ")
            and request.cookies.get("zettnas_session")
            and not _origin_matches_host(request)
        ):
            logger.warning(f"[Auth] Blocked cross-site {request.method} {path} from {client_host}")
            return error_response(403, "Cross-site request blocked.", error="csrf_blocked")

        request.state.session = sess
        request.state.user = sess
        request.state.token = token

    return await call_next(request)


# ==============================================================================
# RBAC Scope Evaluation & FastAPI Dependencies
# ==============================================================================


def has_scope(user_scopes: list[str], required_scope: str) -> bool:
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

    def __init__(self, data: dict[str, Any] | None = None, **kwargs):
        payload = dict(data) if isinstance(data, dict) else {}
        payload.update(kwargs)
        self.user_id: str = payload.get("user_id", "")
        self.username: str = payload.get("username", "")
        self.role_id: str = payload.get("role_id", "share_user")
        self.scopes: list[str] = payload.get("scopes", [])
        self.is_api_token: bool = payload.get("is_api_token", False)
        self.is_system: bool = payload.get("is_system", False)
        self.raw_data: dict[str, Any] = payload

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


def validate_websocket_origin(websocket: Any, is_cookie_auth: bool = False) -> bool:
    """Guards against Cross-Site WebSocket Hijacking (CSWSH).

    If connection was authenticated via Cookie, Origin header is strictly verified against
    the Host header, X-Forwarded-Host, and configured trusted domains/proxies.
    If ticket/token auth is used (which an attacker cannot forge via CSWSH), absence of Origin is permitted.
    """
    origin = websocket.headers.get("origin")
    if not origin:
        return not is_cookie_auth
    # Same rule as the HTTP CSRF check: another port or scheme on this hostname is another site.
    return _origin_in(origin, _allowed_origins(websocket))
