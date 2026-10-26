"""Share links: create, list, revoke, and the public pages and downloads behind them.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import mimetypes
import os
import secrets
import threading
import time
import zipfile
from typing import IO, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

import backend.config as config
from backend.api.files.common import _contained, _user_file_headers
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.fsutil import atomic_write_json, prune_protected, read_json, resolve_within
from backend.passwords import hash_password, verify_password
from backend.rate_limit import rate_limit
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access, user_can_access_path

router = APIRouter()


SHARE_LINKS_FILE = os.path.join(config.DATA_DIR, "shared_links.json")


_SHARE_LOCK = asyncio.Lock()


def _load_share_links() -> dict[str, Any]:
    try:
        return read_json(SHARE_LINKS_FILE, {})
    except Exception:
        return {}


def _save_share_links(links: dict[str, Any]) -> None:
    """Saves share links; a failure is an error the caller sees, never a silent "ok" (SEC-10)."""
    try:
        atomic_write_json(SHARE_LINKS_FILE, links)
    except Exception as e:
        logger.error(f"[FS] Failed to persist share links: {e}")
        raise HTTPException(
            status_code=500, detail="The share links could not be saved (is the disk full?). Nothing was changed."
        ) from e


class CreateShareLinkRequest(BaseModel):
    path: str
    expires_hours: int | None = None
    max_downloads: int | None = None
    password: str | None = None
    label: str | None = None


# Sliding-window rate limiter for shared link password attempts: IP -> list of timestamps
_SHARE_PWD_ATTEMPTS: dict[str, list[float]] = {}


_SHARE_PWD_LOCK = asyncio.Lock()


def _get_client_ip(request: Request) -> str:
    from backend.auth import client_ip

    return client_ip(request)


async def _check_share_rate_limit(ip: str):
    now = time.time()
    async with _SHARE_PWD_LOCK:
        attempts = _SHARE_PWD_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < 600]
        _SHARE_PWD_ATTEMPTS[ip] = attempts
        if len(attempts) >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many failed password attempts. Please wait 10 minutes before retrying.",
            )


async def _record_failed_share_attempt(ip: str):
    now = time.time()
    async with _SHARE_PWD_LOCK:
        attempts = _SHARE_PWD_ATTEMPTS.get(ip, [])
        attempts = [t for t in attempts if now - t < 600]
        attempts.append(now)
        _SHARE_PWD_ATTEMPTS[ip] = attempts


async def _reset_share_rate_limit(ip: str):
    async with _SHARE_PWD_LOCK:
        _SHARE_PWD_ATTEMPTS.pop(ip, None)


@router.post(
    "/fs/share-links",
    dependencies=[
        Depends(require_scope("files:read", "files:write", "storage:read", "storage:admin")),
        Depends(rate_limit("share.create", 30, 3600)),
    ],
)
@router.post(
    "/share-links",
    dependencies=[
        Depends(require_scope("files:read", "files:write", "storage:read", "storage:admin")),
        Depends(rate_limit("share.create", 30, 3600)),
    ],
)
async def create_share_link(
    req: CreateShareLinkRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Generates a secure, temporary or password-protected public share link for a file or folder."""
    target_path = req.path.strip()
    check_user_path_access(target_path, principal)
    real_target = _contained(target_path, must_exist=True)

    if resolve_within(real_target, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Path outside allowed folders")

    token = secrets.token_urlsafe(24)
    now = time.time()
    expires_at = (now + (req.expires_hours * 3600)) if req.expires_hours and req.expires_hours > 0 else None

    password_hash = None
    if req.password and req.password.strip():
        password_hash = hash_password(req.password.strip())

    link_data = {
        "token": token,
        "path": target_path,
        "is_dir": os.path.isdir(real_target),
        "filename": os.path.basename(real_target),
        "label": req.label or os.path.basename(real_target),
        "created_by": principal.username,
        "created_at": now,
        "expires_at": expires_at,
        "max_downloads": req.max_downloads if req.max_downloads and req.max_downloads > 0 else None,
        "download_count": 0,
        "has_password": password_hash is not None,
        "password_hash": password_hash,
    }

    async with _SHARE_LOCK:
        links = _load_share_links()
        links[token] = link_data
        _save_share_links(links)

    sanitized = dict(link_data)
    sanitized.pop("password_hash", None)
    sanitized["url"] = f"/api/fs/shared/{token}"
    return sanitized


@router.get("/fs/share-links", dependencies=[Depends(require_scope("files:read", "storage:read", "storage:admin"))])
@router.get("/share-links", dependencies=[Depends(require_scope("files:read", "storage:read", "storage:admin"))])
def list_share_links(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Lists active public share links created by the current user or all if admin."""
    links = _load_share_links()
    is_admin = principal.has_scope("superadmin") or principal.has_scope("storage:admin") or principal.has_scope("*")
    now = time.time()

    results = []
    for token, item in links.items():
        if not is_admin and item.get("created_by") != principal.username:
            continue
        expired = item.get("expires_at") and now > item["expires_at"]
        limit_reached = item.get("max_downloads") and item.get("download_count", 0) >= item["max_downloads"]

        res = dict(item)
        res.pop("password_hash", None)
        res["url"] = f"/api/fs/shared/{token}"
        res["is_expired"] = bool(expired)
        res["limit_reached"] = bool(limit_reached)
        res["is_active"] = not expired and not limit_reached
        results.append(res)

    results.sort(key=lambda x: x.get("created_at", 0), reverse=True)
    return results


@router.delete("/fs/share-links/{token}", dependencies=[Depends(require_scope("files:write", "storage:admin"))])
@router.delete("/share-links/{token}", dependencies=[Depends(require_scope("files:write", "storage:admin"))])
async def revoke_share_link(
    token: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Revokes and deletes an existing share link."""
    async with _SHARE_LOCK:
        links = _load_share_links()
        if token not in links:
            raise HTTPException(status_code=404, detail="Share link not found")
        item = links[token]
        is_admin = principal.has_scope("superadmin") or principal.has_scope("storage:admin") or principal.has_scope("*")
        if not is_admin and item.get("created_by") != principal.username:
            raise HTTPException(status_code=403, detail="Cannot revoke share link created by another user")
        del links[token]
        _save_share_links(links)

    return {"status": "ok", "revoked": token}


_SHARE_PASSWORD_PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>Shared file</title><style>body{font-family:system-ui;background:#0b0f14;
color:#e5e7eb;display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}form{background:#111827;
padding:24px;border-radius:12px;width:min(320px,90vw)}input,button{width:100%;box-sizing:border-box;padding:10px;margin-top:10px;
border-radius:8px;border:1px solid #374151;background:#0b0f14;color:#fff}button{background:#0ea5e9;border:0;font-weight:700;
color:#000;cursor:pointer}</style></head><body><form method="post"><div>This shared item is password protected.</div>
<input type="password" name="password" autocomplete="current-password" placeholder="Password" required autofocus>
<button type="submit">Open</button></form></body></html>"""


@router.post("/fs/shared/{token}")
@router.post("/shared/{token}")
async def access_shared_file_with_password(token: str, request: Request, info: bool = False):
    """Same as the GET route, with the password in a form or JSON body instead of the URL (SEC-21)."""
    password = ""
    ctype = request.headers.get("content-type", "")
    try:
        if "application/json" in ctype:
            password = str((await request.json()).get("password") or "")
        else:
            # urlencoded form from the password page (no python-multipart dependency)
            from urllib.parse import parse_qs

            body = (await request.body())[:4096].decode("utf-8", errors="replace")
            password = (parse_qs(body).get("password") or [""])[0]
    except Exception:
        password = ""
    return await _serve_shared_item(token, request, info, password)


@router.get("/fs/shared/{token}")
@router.get("/shared/{token}")
async def access_shared_file(
    token: str,
    request: Request,
    info: bool = False,
):
    """
    Public access endpoint for shared files and folders (no session needed).
    Allows streaming the file or downloading a zip of a folder. A password goes in
    the X-Share-Password header or a POST body, never in the URL; browsers get a
    small password form.
    """
    return await _serve_shared_item(token, request, info, request.headers.get("X-Share-Password") or "")


def _share_creator_can_read(created_by: str | None, real_target: str) -> bool:
    """A link works only while the person who made it is active and can still read the item.
    Links saved before creators were recorded (no created_by) keep working."""
    if not created_by:
        return True
    from backend.users_db import get_user_by_username

    user = get_user_by_username(created_by)
    if not user or user.get("status") != "active":
        return False
    creator = AuthenticatedPrincipal(
        {
            "user_id": user["id"],
            "username": user["username"],
            "role_id": user.get("role_id"),
            "scopes": user.get("scopes") or [],
        }
    )
    return user_can_access_path(real_target, creator)


SHARE_ZIP_LIMIT = 5 * 1024**3


SHARE_ZIP_MAX_RUNNING = 2


SHARE_ZIP_SLOT_TTL = 6 * 3600  # a download that never started (client gone) frees its slot later


_SHARE_ZIP_ACTIVE: dict[str, float] = {}


_SHARE_ZIP_LOCK = threading.Lock()


def _share_zip_slot() -> str | None:
    """A slot for one folder download, or None when two are already running."""
    now = time.time()
    with _SHARE_ZIP_LOCK:
        for k in [k for k, t in _SHARE_ZIP_ACTIVE.items() if now - t > SHARE_ZIP_SLOT_TTL]:
            _SHARE_ZIP_ACTIVE.pop(k, None)
        if len(_SHARE_ZIP_ACTIVE) >= SHARE_ZIP_MAX_RUNNING:
            return None
        slot = secrets.token_hex(8)
        _SHARE_ZIP_ACTIVE[slot] = now
        return slot


def _release_share_zip_slot(slot: str) -> None:
    with _SHARE_ZIP_LOCK:
        _SHARE_ZIP_ACTIVE.pop(slot, None)


def _folder_size_capped(folder: str, limit: int) -> int:
    """Total size of a folder; raises ValueError as soon as it passes `limit`."""
    total = 0
    for root_dir, sub_dirs, files in os.walk(folder):
        prune_protected(root_dir, sub_dirs)
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root_dir, f))
            except OSError:
                continue
            if total > limit:
                raise ValueError("too large")
    return total


class _ZipSink:
    """A write-only stream for zipfile: the bytes written so far, handed out as they come."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.pos = 0

    def write(self, data: bytes, /) -> int:
        self.buf += data
        self.pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self.pos

    def flush(self) -> None:
        return None

    def take(self) -> bytes:
        out = bytes(self.buf)
        self.buf.clear()
        return out


def _stream_folder_zip(folder: str, slot: str = ""):
    """Yields a zip of `folder` while it is built; never holds more than one read buffer (SEC-9)."""
    folder_abs = os.path.realpath(folder)
    sink = _ZipSink()
    try:
        # zipfile only writes, tells and flushes on a stream it was handed (never closes it)
        with zipfile.ZipFile(cast(IO[bytes], sink), mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root_dir, sub_dirs, files in os.walk(folder):
                prune_protected(root_dir, sub_dirs)
                for f in files:
                    fp = os.path.join(root_dir, f)
                    real_fp = os.path.realpath(fp)
                    if not (real_fp == folder_abs or real_fp.startswith(folder_abs + os.sep)):
                        logger.warning(f"[Share Download] Skipping symlink outside shared directory: {fp} -> {real_fp}")
                        continue
                    rel = os.path.relpath(fp, os.path.dirname(folder))
                    try:
                        with open(fp, "rb") as src, zf.open(rel, "w", force_zip64=True) as dst:
                            while block := src.read(1024 * 1024):
                                dst.write(block)
                                if len(sink.buf) >= 256 * 1024:
                                    yield sink.take()
                    except OSError:
                        logger.warning(f"[Share Download] Skipping unreadable file {fp}", exc_info=True)
                    if sink.buf:
                        yield sink.take()
        if sink.buf:
            yield sink.take()
    finally:
        _release_share_zip_slot(slot)


async def _serve_shared_item(token: str, request: Request, info: bool, provided_pwd: str):
    from backend.rate_limit import hit as _rl_hit

    wait = _rl_hit(f"share.access:{_get_client_ip(request)}", 120, 60)
    if wait:
        raise HTTPException(
            status_code=429, detail=f"Too many requests. Try again in {wait}s.", headers={"Retry-After": str(wait)}
        )
    links = _load_share_links()
    if token not in links:
        raise HTTPException(status_code=404, detail="Share link not found or revoked")

    item = links[token]
    now = time.time()

    if item.get("expires_at") and now > item["expires_at"]:
        raise HTTPException(status_code=410, detail="Share link has expired")

    if item.get("max_downloads") and item.get("download_count", 0) >= item["max_downloads"]:
        raise HTTPException(status_code=410, detail="Download limit reached for this share link")

    client_ip = _get_client_ip(request)

    if item.get("has_password"):
        await _check_share_rate_limit(client_ip)
        if not provided_pwd:
            if "text/html" in request.headers.get("accept", "") and not info:
                return Response(content=_SHARE_PASSWORD_PAGE, media_type="text/html", status_code=401)
            raise HTTPException(
                status_code=401,
                detail="Password required to access this share",
                headers={"WWW-Authenticate": "ShareLink realm='Shared Resource'"},
            )
        expected_hash = item.get("password_hash") or ""
        if not verify_password(provided_pwd.strip(), expected_hash):
            await _record_failed_share_attempt(client_ip)
            raise HTTPException(status_code=401, detail="Incorrect password for this share link")
        await _reset_share_rate_limit(client_ip)

    target_path = item["path"]
    try:
        real_target = _contained(target_path, must_exist=True)
    except HTTPException:
        raise HTTPException(status_code=404, detail="Underlying shared file or folder is no longer available") from None

    if resolve_within(real_target, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Target path is outside allowed system roots")
    if not _share_creator_can_read(item.get("created_by"), real_target):
        raise HTTPException(status_code=410, detail="This share link is no longer available")

    is_dir = os.path.isdir(real_target)

    if info:
        size = 0
        if not is_dir:
            try:
                size = os.path.getsize(real_target)
            except OSError:
                pass
        return {
            "token": token,
            "filename": item.get("filename", os.path.basename(real_target)),
            "label": item.get("label"),
            "is_dir": is_dir,
            "size_bytes": size,
            "has_password": bool(item.get("has_password")),
            "expires_at": item.get("expires_at"),
            "download_count": item.get("download_count", 0),
            "max_downloads": item.get("max_downloads"),
        }

    if is_dir:
        base_name = os.path.basename(real_target) or "shared_folder"
        # the size check walks the folder: in a thread, so a big folder never freezes the server
        try:
            await asyncio.to_thread(_folder_size_capped, real_target, SHARE_ZIP_LIMIT)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Shared folder exceeds maximum download size limit (5 GB)."
            ) from None
        slot = _share_zip_slot()
        if not slot:
            raise HTTPException(
                status_code=429,
                detail="Too many folder downloads at once. Try again in a minute.",
                headers={"Retry-After": "60"},
            )

    async with _SHARE_LOCK:
        cur_links = _load_share_links()
        if token in cur_links:
            cur_links[token]["download_count"] = cur_links[token].get("download_count", 0) + 1
            try:
                _save_share_links(cur_links)
            except HTTPException:
                logger.warning("[FS] Download count not saved; serving the download anyway")

    if is_dir:
        return StreamingResponse(
            _stream_folder_zip(real_target, slot),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{base_name}.zip"'},
        )
    else:
        media_type, _ = mimetypes.guess_type(real_target)
        if not media_type:
            media_type = "application/octet-stream"
        fname = os.path.basename(real_target)
        return FileResponse(
            real_target,
            media_type=media_type,
            filename=fname,
            headers={"Content-Disposition": f'inline; filename="{fname}"', **_user_file_headers(media_type)},
        )
