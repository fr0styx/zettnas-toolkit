"""
ZettNAS Toolkit - WebDAV API & Streaming Reverse Proxy
Provides WebDAV daemon controls, modern WebDAV Portal UI, and transparent HTTP proxying on /webdav.
"""

import asyncio
import logging
import os
import urllib.parse
from typing import Any, Dict, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field

import backend.config as config
from backend.auth import require_scope
from backend.passwords import verify_password
from backend.services.webdav_engine import get_webdav_engine
from backend.services.webdav_portal import render_webdav_login, render_webdav_portal

logger = logging.getLogger("ZettNAS.WebDAVApi")

router = APIRouter(tags=["WebDAV Storage"])
proxy_router = APIRouter(tags=["WebDAV Proxy"], include_in_schema=False)


class WebdavConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    port: Optional[int] = Field(None, ge=1024, le=65535)
    root_path: Optional[str] = None
    read_only: Optional[bool] = None
    username: Optional[str] = None
    password: Optional[str] = None
    auth_enabled: Optional[bool] = None


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

    engine = get_webdav_engine()
    cfg = engine.load_config()
    expected_user = cfg.get("username", "admin") or "admin"
    webdav_pass = cfg.get("password")

    authenticated = False
    is_admin = False

    # 1. Check user in SQLite users.db
    from backend.users_db import get_user_by_username

    user = get_user_by_username(username)
    if user and user.get("status") == "active":
        if verify_password(password, user.get("password_hash", "")):
            authenticated = True
            is_admin = user.get("role_id") in ("superadmin", "storage_admin")

    # 2. Fallback check for legacy admin credentials
    if not authenticated and username.lower() in (
        "admin",
        expected_user.lower(),
        getattr(config, "ZETTNAS_USERNAME", "admin").lower(),
    ):
        if webdav_pass and password == webdav_pass:
            authenticated = True
            is_admin = True
        elif config.STORED_PASSWORD_HASH and verify_password(password, config.STORED_PASSWORD_HASH):
            authenticated = True
            is_admin = True
            # Sync this password to webdav config if no dedicated password was set
            if not webdav_pass and password != "admin":
                try:
                    engine.save_config({"password": password})
                    asyncio.create_task(asyncio.to_thread(engine.restart))
                except Exception as e:
                    logger.warning(f"[WebDAV] Failed to sync master password: {e}")
        elif password == (config.WEB_PASSWORD or "admin"):
            authenticated = True
            is_admin = True

    if authenticated:
        role_label = "admin" if is_admin else "user"
        resp = RedirectResponse(url="/webdav/", status_code=303)
        resp.set_cookie(
            key="webdav_session",
            value=f"{username}:{role_label}",
            max_age=86400 * 7,
            httponly=True,
            samesite="lax",
        )
        return resp
    else:
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
    if any(client in ua for client in dav_clients):
        return True

    return False


def _get_webdav_portal_user(request: Request, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not cfg.get("auth_enabled", True):
        return {"username": cfg.get("username", "admin") or "admin", "is_admin": True, "role_id": "superadmin"}

    # 1. Check dedicated webdav_session cookie
    session_cookie = request.cookies.get("webdav_session")
    if session_cookie and ":" in session_cookie:
        username, _ = session_cookie.split(":", 1)
        if username:
            from backend.users_db import get_user_by_username

            user = get_user_by_username(username)
            if user and user.get("status") == "active":
                is_admin = user.get("role_id") in ("superadmin", "storage_admin")
                return {
                    "username": user["username"],
                    "role_id": user.get("role_id", "share_user"),
                    "is_admin": is_admin,
                    "home_directory": user.get("home_directory"),
                }

            expected_user = cfg.get("username", "admin") or "admin"
            if username.lower() in (
                "admin",
                expected_user.lower(),
                getattr(config, "ZETTNAS_USERNAME", "admin").lower(),
            ):
                return {"username": username, "role_id": "superadmin", "is_admin": True}

    # 2. Check active ZettNAS desktop session (session cookie, bearer token, or state)
    try:
        sess = getattr(request.state, "session", None)
        if not sess:
            from backend.auth import extract_token, get_current_session

            tok = extract_token(request)
            if tok:
                sess = get_current_session(tok)
        if sess:
            u_name = sess.get("username", "admin")
            role_id = sess.get("role_id", "share_user")
            is_admin = role_id in ("superadmin", "storage_admin")
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


async def _proxy_webdav(request: Request, path: str = ""):
    engine = get_webdav_engine()
    if not engine.is_running():
        cfg = engine.load_config()
        if cfg.get("enabled", True):
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
        raise HTTPException(status_code=502, detail="Unable to connect to internal WebDAV daemon.")
    except Exception as e:
        await client.aclose()
        logger.error(f"[WEBDAV PROXY] Error proxying {request.method} {path}: {e}")
        raise HTTPException(status_code=500, detail=f"WebDAV proxy error: {e}")


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
    abs_target = os.path.abspath(os.path.join(root_path, clean_path)) if clean_path else root_path

    # Security: Path traversal protection
    if abs_target != root_path and not abs_target.startswith(root_path + os.sep):
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
        return FileResponse(
            path=abs_target,
            filename=filename,
            content_disposition_type=disposition,
        )

    # Path does not exist
    raise HTTPException(status_code=404, detail="The requested file or directory does not exist.")
