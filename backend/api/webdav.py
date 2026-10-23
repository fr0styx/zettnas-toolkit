"""
ZettNAS Toolkit - WebDAV API & Streaming Reverse Proxy
Provides WebDAV daemon controls, modern WebDAV Portal UI, and transparent HTTP proxying on /webdav.
"""

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import time
import urllib.parse
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

import backend.config as config
from backend.auth import require_scope
from backend.fsutil import resolve_within
from backend.passwords import verify_password
from backend.services.webdav_engine import get_webdav_engine
from backend.services.webdav_portal import render_webdav_login, render_webdav_portal

logger = logging.getLogger("ZettNAS.WebDAVApi")

router = APIRouter(tags=["WebDAV Storage"])
proxy_router = APIRouter(tags=["WebDAV Proxy"], include_in_schema=False)


WEBDAV_COOKIE_TTL = 12 * 3600


def _request_is_https(request) -> bool:
    from backend.auth import request_is_https

    return request_is_https(request)


def _cookie_key(username: str) -> bytes:
    """Signing key for one user's portal cookie. It includes the account's password hash,
    so changing the password ends existing portal cookies."""
    from backend.users_db import get_user_by_username

    secret = getattr(config, "SECRET_KEY", "zettnas-webdav-fallback-secret")
    pw_hash = (get_user_by_username(username) or {}).get("password_hash") or ""
    return f"{secret}:{pw_hash}".encode()


def _sign_webdav_cookie(username: str, role_label: str, issued_at: int | None = None) -> str:
    """Creates an HMAC-SHA256 signed, expiring session cookie: user:role:issued_at:sig."""
    iat = int(issued_at if issued_at is not None else time.time())
    payload = f"{username}:{role_label}:{iat}"
    sig = hmac.new(_cookie_key(username), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{sig}"


def _verify_webdav_cookie(cookie_val: str) -> tuple[str, str] | None:
    """Verifies signature and age of a WebDAV session cookie.
    Rejects legacy (non-expiring), unsigned, expired or corrupt cookies without raising.
    """
    if not cookie_val or cookie_val.count(":") != 3:
        return None
    try:
        username, role_label, iat_raw, sig = cookie_val.split(":", 3)
        if not username or not role_label or not sig or not iat_raw.isdigit():
            return None
        age = time.time() - int(iat_raw)
        if age < -60 or age > WEBDAV_COOKIE_TTL:
            return None
        payload = f"{username}:{role_label}:{iat_raw}"
        expected_sig = hmac.new(_cookie_key(username), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected_sig):
            return username, role_label
    except Exception as e:
        logger.debug(f"[WebDAV] Cookie signature verification failed: {e}")
    return None


class WebdavConfigRequest(BaseModel):
    enabled: bool | None = None
    port: int | None = Field(None, ge=1024, le=65535)
    root_path: str | None = None
    read_only: bool | None = None
    username: str | None = None
    password: str | None = None
    auth_enabled: bool | None = None


class WebdavToggleRequest(BaseModel):
    enabled: bool


@router.get("/webdav/status")
async def get_webdav_status():
    """Returns WebDAV daemon operational status, port, URLs, and quick-connect commands."""
    engine = get_webdav_engine()
    return engine.get_status()


@router.post("/webdav/toggle", dependencies=[Depends(require_scope("shares:manage", "storage:admin"))])
async def toggle_webdav(req: WebdavToggleRequest):
    """Enables or disables the WebDAV service."""
    engine = get_webdav_engine()
    engine.save_config({"enabled": req.enabled})
    if req.enabled:
        return await asyncio.to_thread(engine.start)
    else:
        return await asyncio.to_thread(engine.stop)


@router.post("/webdav/config", dependencies=[Depends(require_scope("shares:manage", "storage:admin"))])
async def update_webdav_config(req: WebdavConfigRequest):
    """Updates WebDAV configuration and restarts the daemon if running."""
    engine = get_webdav_engine()
    updates = req.model_dump(exclude_unset=True)
    engine.save_config(updates)
    if engine.is_running():
        return await asyncio.to_thread(engine.restart)
    return engine.get_status()


@router.post("/webdav/restart", dependencies=[Depends(require_scope("shares:manage", "storage:admin"))])
async def restart_webdav():
    """Restarts the WebDAV daemon."""
    engine = get_webdav_engine()
    return await asyncio.to_thread(engine.restart)


# WebDAV Portal Authentication Routes
@proxy_router.api_route("/webdav/auth/login", methods=["GET", "POST"])
async def webdav_portal_login(request: Request):
    if request.method == "GET":
        return RedirectResponse(url="/webdav/", status_code=303)
    if not get_webdav_engine().load_config().get("enabled", False):
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = await request.json()
            username = str(payload.get("username", "")).strip()
            password = str(payload.get("password", "")).strip()
        else:
            raw_body = await request.body()
            parsed = urllib.parse.parse_qs(raw_body.decode("utf-8", errors="ignore"))
            username = parsed.get("username", [""])[0].strip()
            password = parsed.get("password", [""])[0].strip()
    except Exception as parse_err:
        logger.warning(f"[WebDAV Login] Body parse error: {parse_err}")
        username = ""
        password = ""

    from backend.services import login_lockout
    from backend.users_db import get_user_by_username

    lock_key = f"webdav:{username.lower()}"
    wait = login_lockout.remaining(lock_key)
    if wait > 0:
        return HTMLResponse(
            render_webdav_login(error_msg=f"Too many failed attempts. Try again in {wait} seconds."),
            status_code=429,
        )

    # Only real ZettNAS accounts; no default, legacy or copied master password (SEC-02).
    authenticated = False
    is_admin = False
    user = get_user_by_username(username)
    if user and user.get("status") == "active" and password:
        if verify_password(password, user.get("password_hash", "")):
            if user.get("must_change_password"):
                return HTMLResponse(
                    render_webdav_login(error_msg="Change your ZettNAS password before using WebDAV."),
                    status_code=403,
                )
            if user.get("mfa_enabled"):
                # The portal has no second-factor step; a password alone must not open the files.
                return HTMLResponse(
                    render_webdav_login(
                        error_msg="Accounts with two-factor sign-in open WebDAV files from inside ZettNAS."
                    ),
                    status_code=403,
                )
            authenticated = True
            is_admin = user.get("role_id") in ("superadmin", "storage_admin")

    if authenticated:
        login_lockout.clear(lock_key)
        role_label = "admin" if is_admin else "user"
        resp = RedirectResponse(url="/webdav/", status_code=303)
        resp.set_cookie(
            key="webdav_session",
            value=_sign_webdav_cookie(user["username"], role_label),
            max_age=WEBDAV_COOKIE_TTL,
            httponly=True,
            samesite="lax",
            secure=_request_is_https(request),
        )
        return resp
    else:
        from backend.auth import client_ip
        from backend.services import ip_block

        ip_block.record_auth_failure(client_ip(request), "WebDAV")  # M5
        return HTMLResponse(
            render_webdav_login(error_msg="Invalid WebDAV username or password."),
            status_code=200,
        )


@proxy_router.get("/webdav/auth/logout")
async def webdav_portal_logout():
    resp = RedirectResponse(url="/webdav/", status_code=303)
    resp.delete_cookie("webdav_session")
    return resp


# Transparent Reverse Proxy for /webdav
WEBDAV_METHODS = [
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "HEAD",
    "OPTIONS",
    "PROPFIND",
    "PROPPATCH",
    "MKCOL",
    "COPY",
    "MOVE",
    "LOCK",
    "UNLOCK",
]


def _is_webdav_client(request: Request) -> bool:
    """Detects whether a request originates from a native WebDAV client or CLI tool,
    as opposed to an interactive web browser session.
    """
    # 1. Non-GET/HEAD WebDAV protocol methods (PROPFIND, MKCOL, PUT, etc.)
    if request.method not in ("GET", "HEAD"):
        return True

    # 2. Presence of HTTP Basic Authorization header (Finder, Cyberduck, etc.)
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("basic "):
        return True

    # 3. WebDAV-specific protocol headers
    if any(h in request.headers for h in ("depth", "destination", "translate", "if", "lock-token", "overwrite")):
        return True

    # 4. Known WebDAV client / CLI user-agents
    ua = request.headers.get("user-agent", "").lower()
    dav_clients = (
        "webdav",
        "davfs",
        "cyberduck",
        "rclone",
        "curl",
        "wget",
        "python",
        "git",
        "transmit",
        "winhttp",
        "microsoft-webdav",
        "gvfs",
        "mountainduck",
        "filezilla",
    )
    return bool(any(client in ua for client in dav_clients))


def _get_webdav_portal_user(request: Request, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if not cfg.get("auth_enabled", True):
        return {"username": cfg.get("username", "admin") or "admin", "is_admin": True, "role_id": "superadmin"}

    # 1. Check dedicated webdav_session cookie
    session_cookie = request.cookies.get("webdav_session")
    if session_cookie:
        verified = _verify_webdav_cookie(session_cookie)
        if verified:
            username, _ = verified
            from backend.users_db import get_user_by_username

            user = get_user_by_username(username)
            if user and user.get("status") == "active" and not user.get("mfa_enabled"):
                is_admin = user.get("role_id") in ("superadmin", "storage_admin")
                return {
                    "username": user["username"],
                    "role_id": user.get("role_id", "share_user"),
                    "is_admin": is_admin,
                    "home_directory": user.get("home_directory"),
                }
            # Unknown, disabled or deleted users get nothing (no admin-name fallback).

    # 2. Check active ZettNAS desktop session (session cookie, bearer token, or state)
    try:
        sess = getattr(request.state, "session", None)
        if not sess:
            from backend.auth import extract_token, get_current_session

            tok = extract_token(request)
            if tok:
                sess = get_current_session(tok)
        # Only a person's sign-in session; API tokens and tickets do not open the portal.
        if sess and not any(
            sess.get(f) for f in ("is_api_token", "is_stream_ticket", "is_console_ticket", "is_system")
        ):
            from backend.auth import has_scope

            u_name = sess.get("username", "admin")
            role_id = sess.get("role_id", "share_user")
            is_admin = has_scope(list(sess.get("scopes") or []), "storage:admin")
            from backend.users_db import get_user_by_username

            u_rec = get_user_by_username(u_name)
            home_dir = u_rec.get("home_directory") if u_rec else None
            return {
                "username": u_name,
                "role_id": role_id,
                "is_admin": is_admin,
                "home_directory": home_dir,
            }
    except Exception as e:
        logger.debug(f"[WebDAV Auth] Desktop session lookup fallback failed: {e}")

    return None


def _observe_webdav_write(request: Request, path: str) -> None:
    """Feeds WebDAV renames, deletes and writes to the ransomware guard (M4)."""
    kind = {"MOVE": "rename", "DELETE": "delete", "PUT": "write"}.get(request.method)
    if not kind:
        return
    from backend.auth import client_ip
    from backend.services.ransomware_guard import get_guard

    dest = request.headers.get("destination", "")
    new_path = urllib.parse.unquote(dest.split("/webdav/", 1)[1]) if "/webdav/" in dest else ""
    user = ""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            user = base64.b64decode(auth[6:]).decode("utf-8", "replace").split(":", 1)[0]
        except ValueError:
            user = ""
    get_guard().observe(kind, path, user=user, ip=client_ip(request), new_path=new_path)


async def _proxy_webdav(request: Request, path: str = ""):
    _observe_webdav_write(request, path)
    engine = get_webdav_engine()
    if not engine.is_running():
        cfg = engine.load_config()
        if cfg.get("enabled", False):
            await asyncio.to_thread(engine.start)
        if not engine.is_running():
            raise HTTPException(
                status_code=503,
                detail="WebDAV server is currently stopped or unavailable.",
            )

    cfg = engine.load_config()
    port = int(cfg.get("port", config.WEBDAV_PORT))
    clean_path = path.lstrip("/")
    target_url = f"http://127.0.0.1:{port}/{clean_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = dict(request.headers)
    headers["host"] = f"127.0.0.1:{port}"

    # Handle Destination header rewriting for COPY / MOVE
    if "destination" in headers:
        dest = headers["destination"]
        if "/webdav/" in dest:
            dest_suffix = dest.split("/webdav/", 1)[1]
            headers["destination"] = f"http://127.0.0.1:{port}/{dest_suffix}"

    client = httpx.AsyncClient(timeout=None)
    try:
        req = client.build_request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=request.stream(),
        )
        resp = await client.send(req, stream=True)

        resp_headers = {}
        hop_by_hop = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
        for k, v in resp.headers.items():
            if k.lower() not in hop_by_hop:
                resp_headers[k] = v

        async def body_stream():
            try:
                async for chunk in resp.aiter_raw():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(
            body_stream(),
            status_code=resp.status_code,
            headers=resp_headers,
        )
    except httpx.ConnectError:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Unable to connect to internal WebDAV daemon.") from None
    except Exception as e:
        await client.aclose()
        logger.error(f"[WEBDAV PROXY] Error proxying {request.method} {path}: {e}")
        raise HTTPException(status_code=500, detail=f"WebDAV proxy error: {e}") from e


@proxy_router.api_route("/webdav", methods=WEBDAV_METHODS)
async def webdav_proxy_root(request: Request):
    if request.method in ("GET", "HEAD"):
        return RedirectResponse(url="/webdav/", status_code=307)
    return await _proxy_webdav(request, "")


@proxy_router.api_route("/webdav/{path:path}", methods=WEBDAV_METHODS)
async def webdav_proxy_subpath(request: Request, path: str):
    # Exclude internal auth routes
    if path.startswith("auth/"):
        raise HTTPException(status_code=404, detail="Not Found")

    engine = get_webdav_engine()
    cfg = engine.load_config()
    if not cfg.get("enabled", False):
        raise HTTPException(status_code=404, detail="Not Found")

    # Native WebDAV clients (Finder, Cyberduck, rclone, curl, etc.) or Basic Auth -> proxy to daemon
    if _is_webdav_client(request):
        return await _proxy_webdav(request, path)

    # Web browser requests: verify portal authentication
    user_info = _get_webdav_portal_user(request, cfg)
    if not user_info:
        return HTMLResponse(render_webdav_login(), status_code=200)

    configured_root = cfg.get("root_path")
    if configured_root and os.path.exists(str(configured_root)):
        base_pool = str(configured_root)
    else:
        base_pool = str(config.POOL_PATH)

    if user_info.get("is_admin"):
        root_path = os.path.abspath(base_pool)
    else:
        home = user_info.get("home_directory")
        if not home or not os.path.exists(home):
            home = os.path.join(base_pool, "homes", user_info["username"].lower())
        try:
            os.makedirs(home, exist_ok=True)
        except OSError:
            pass
        root_path = os.path.abspath(home)

    clean_path = urllib.parse.unquote(path).strip("/")
    target = os.path.join(root_path, clean_path) if clean_path else root_path
    abs_target = os.path.realpath(target)

    # Security: Canonical path traversal & symlink escape protection
    if resolve_within(abs_target, [root_path]) is None:
        logger.warning(f"[WEBDAV] Directory traversal attempt rejected: {path} -> {abs_target}")
        raise HTTPException(status_code=403, detail="Access denied: path traversal detected.")

    # Target directory -> Render ZettNAS WebDAV Cloud Portal UI
    if os.path.isdir(abs_target):
        return HTMLResponse(render_webdav_portal(clean_path, root_path, user_info["username"]), status_code=200)

    # Target file -> Direct line-rate serving with FileResponse (inline preview or raw attachment download)
    if os.path.isfile(abs_target):
        is_raw_download = request.query_params.get("raw") == "1"
        disposition = "attachment" if is_raw_download else "inline"
        filename = os.path.basename(abs_target)
        ext = os.path.splitext(filename)[1].lower()
        if ext in (".html", ".htm", ".svg", ".xhtml", ".xml", ".js"):
            disposition = "attachment"
        headers = {
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
            "X-Content-Type-Options": "nosniff",
        }
        return FileResponse(
            path=abs_target,
            filename=filename,
            content_disposition_type=disposition,
            headers=headers,
        )

    # Path does not exist
    raise HTTPException(status_code=404, detail="The requested file or directory does not exist.")
