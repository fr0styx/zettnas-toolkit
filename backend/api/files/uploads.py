"""Single-file downloads, the phone inbox and uploads (whole and chunked).

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import hashlib
import mimetypes
import os
import secrets
import shutil
import time
from typing import Any

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.api.files.common import _contained, _observe, _safe_fs_target, _user_file_headers, record_activity
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import POOL_PATH, logger
from backend.fsutil import resolve_within
from backend.ignored_errors import ignored
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access
from backend.state import add_event

router = APIRouter()


@router.get("/fs/download")
def fs_download(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    return FileResponse(
        target, filename=os.path.basename(target), headers=_user_file_headers(mimetypes.guess_type(target)[0])
    )


def _inbox_dir(principal: AuthenticatedPrincipal) -> str:
    """The user's Inbox for files shared from a phone (M1): <home>/Inbox."""
    from backend.users_db import get_user_by_username

    rec = get_user_by_username(principal.username) or {}
    home = rec.get("home_directory") or os.path.join(POOL_PATH or ALLOWED_BROWSE_ROOTS[0], "homes", principal.username)
    inbox = os.path.join(home, "Inbox")
    canonical = resolve_within(inbox, ALLOWED_BROWSE_ROOTS)
    if canonical is None:
        raise HTTPException(status_code=400, detail="Your home folder is outside the allowed folders")
    return canonical


@router.get("/fs/inbox", dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin"))])
def fs_inbox(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return {"path": _inbox_dir(principal)}


@router.post("/fs/inbox", dependencies=[Depends(require_scope("shares:user_write", "storage:write", "storage:admin"))])
async def fs_inbox_upload(
    request: Request, filename: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """Saves one shared file into the Inbox under a name that doesn't overwrite anything (M1)."""
    inbox = _inbox_dir(principal)
    check_user_path_access(inbox, principal, write=True)
    name = os.path.basename(str(filename or "").replace("\\", "/")).strip() or "shared-file"
    if name in (".", "..") or name.startswith("."):
        name = f"shared{name}"
    await asyncio.to_thread(os.makedirs, inbox, exist_ok=True)
    stem, ext = os.path.splitext(name)
    target = os.path.join(inbox, name)
    n = 1
    while os.path.lexists(target):
        n += 1
        target = os.path.join(inbox, f"{stem} ({n}){ext}")
    staging = os.path.join(inbox, f".zettnas_tmp_{secrets.token_hex(8)}")
    try:
        async with aiofiles.open(staging, "wb") as f_out:
            async for chunk in request.stream():
                if chunk:
                    await f_out.write(chunk)
        os.replace(staging, target)
    finally:
        if os.path.exists(staging):
            os.remove(staging)
    _observe("write", target, principal)
    record_activity("upload", target, principal, detail="to the Inbox")
    add_event("success", "File Explorer", f"Received {os.path.basename(target)} in Inbox")
    return {"status": "ok", "path": target, "name": os.path.basename(target)}


@router.post(
    "/fs/upload",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload(
    request: Request,
    path: str,
    filename: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    check_user_path_access(path, principal, write=True)
    target_unresolved, _, _ = _safe_fs_target(path)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None or not os.path.isdir(target_canonical):
        raise HTTPException(status_code=400, detail="Target path is not a valid directory within allowed folders")

    # Secure filename against traversal
    filename = os.path.basename(filename)
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(target_canonical, filename)
    check_user_path_access(file_path, principal, write=True)
    if os.path.islink(file_path) and resolve_within(file_path, ALLOWED_BROWSE_ROOTS) is None:
        raise HTTPException(status_code=403, detail="Destination symlink points outside allowed folders")

    # Personal space quota (Batch 6): refuse up front when the size is known, stop when it isn't
    from backend.services.user_spaces import QuotaExceeded, check_upload

    declared = int(request.headers.get("content-length") or 0)
    try:
        allowed = check_upload(principal.username, file_path, declared)
    except QuotaExceeded as e:
        raise HTTPException(status_code=507, detail=str(e)) from None

    staging_file = os.path.join(target_canonical, f".zettnas_tmp_{secrets.token_hex(8)}_{filename}")
    try:
        written = 0
        async with aiofiles.open(staging_file, "wb") as f_out:
            async for chunk in request.stream():
                if chunk:
                    written += len(chunk)
                    if allowed is not None and written > allowed:
                        raise QuotaExceeded(0, 0, written)
                    await f_out.write(chunk)

        os.replace(staging_file, file_path)
        record_activity("upload", file_path, principal)
        add_event("success", "File Explorer", f"Uploaded {filename} to {path}")
        return {"status": "ok", "message": "File uploaded"}
    except QuotaExceeded:
        if os.path.exists(staging_file):
            os.remove(staging_file)
        raise HTTPException(status_code=507, detail="This upload would go over your space.") from None
    except Exception as e:
        if os.path.exists(staging_file):
            try:
                os.remove(staging_file)
            except Exception:
                ignored("backend.api.fs.fs_upload")
        logger.error(f"[FS] Upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file") from e


UPLOAD_CHUNK_SIZE = 16 * 1024 * 1024


UPLOAD_SESSION_TTL = 24 * 3600


UPLOAD_FREE_FLOOR = 1024**3  # an upload never fills the pool to the last gigabyte (SEC-7)


class UploadInitRequest(BaseModel):
    # the File Explorer sends destination_dir and no chunk count; scripts send path
    path: str | None = None
    destination_dir: str | None = None
    filename: str
    total_size: int = Field(ge=0)
    total_chunks: int | None = Field(default=None, ge=1, le=1_000_000)
    chunk_size: int | None = None


class UploadCompleteRequest(BaseModel):
    upload_id: str
    expected_sha256: str | None = None


_CHUNKED_UPLOADS: dict[str, dict[str, Any]] = {}


_CHUNKED_UPLOADS_LOCK = asyncio.Lock()


@router.post(
    "/fs/upload/init",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload_init(
    req: UploadInitRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    dest = req.path or req.destination_dir or ""
    if not dest:
        raise HTTPException(status_code=400, detail="Choose a folder to upload to")
    fewest = max(1, -(-int(req.total_size) // UPLOAD_CHUNK_SIZE))
    total_chunks = int(req.total_chunks or fewest)
    if not fewest <= total_chunks <= max(1, int(req.total_size)):
        raise HTTPException(status_code=400, detail="The chunk count doesn't match the file size")
    await _expire_uploads()
    check_user_path_access(dest, principal, write=True)
    target_unresolved, _, _ = _safe_fs_target(dest)
    target_canonical = resolve_within(target_unresolved, ALLOWED_BROWSE_ROOTS)
    if target_canonical is None or not os.path.isdir(target_canonical):
        raise HTTPException(status_code=400, detail="Target path is not a valid directory within allowed folders")

    filename = os.path.basename(req.filename)
    if not filename or filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    from backend.services.user_spaces import QuotaExceeded, check_upload

    try:
        check_upload(principal.username, os.path.join(target_canonical, filename), int(req.total_size or 0))
    except QuotaExceeded as e:
        raise HTTPException(status_code=507, detail=str(e)) from None

    try:
        free = shutil.disk_usage(target_canonical).free
    except OSError:
        free = None
    if free is not None and free - int(req.total_size) < UPLOAD_FREE_FLOOR:
        raise HTTPException(status_code=507, detail="Not enough free space for this file.")

    upload_id = secrets.token_hex(16)
    staging_dir = os.path.join(target_canonical, f".zettnas_staging_{upload_id}_{filename}")
    os.makedirs(staging_dir, exist_ok=True)
    from backend.services import upload_staging

    # noted in the data folder, so a restart or a crash can't leave it in the share (NARC-9)
    temp_name = os.path.join(target_canonical, f".zettnas_tmp_{upload_id}_{filename}")
    await asyncio.to_thread(upload_staging.note, upload_id, [staging_dir, temp_name])

    async with _CHUNKED_UPLOADS_LOCK:
        _CHUNKED_UPLOADS[upload_id] = {
            "upload_id": upload_id,
            "target_dir": target_canonical,
            "staging_dir": staging_dir,
            "filename": filename,
            "total_size": int(req.total_size),
            "total_chunks": total_chunks,
            "chunks_received": set(),
            "chunk_bytes": {},
            "created_at": time.time(),
            "created_by": principal.username,
        }

    return {
        "status": "ok",
        "upload_id": upload_id,
        "chunk_size": UPLOAD_CHUNK_SIZE,
        "total_chunks": total_chunks,
    }


async def _expire_uploads() -> None:
    """Uploads left unfinished for a day are removed with their staged chunks (SEC-7)."""
    cutoff = time.time() - UPLOAD_SESSION_TTL
    async with _CHUNKED_UPLOADS_LOCK:
        stale = [u for u in _CHUNKED_UPLOADS.values() if u.get("created_at", 0) < cutoff]
        for u in stale:
            _CHUNKED_UPLOADS.pop(u["upload_id"], None)
    from backend.services import upload_staging

    for u in stale:
        await asyncio.to_thread(shutil.rmtree, u.get("staging_dir", ""), True)  # off the event loop
        await asyncio.to_thread(upload_staging.forget, u["upload_id"])


@router.post(
    "/fs/upload/chunk",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload_chunk(
    request: Request,
    upload_id: str,
    chunk_index: int,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    async with _CHUNKED_UPLOADS_LOCK:
        upload_info = _CHUNKED_UPLOADS.get(upload_id)
        if not upload_info:
            raise HTTPException(status_code=404, detail="Upload session not found or expired")
        if upload_info.get("created_by") != principal.username and not principal.has_scope("storage:admin"):
            raise HTTPException(status_code=403, detail="Not authorized to write to this upload")

    staging_dir = upload_info["staging_dir"]
    if not os.path.isdir(staging_dir):
        raise HTTPException(status_code=404, detail="Staging directory missing for upload session")
    if not 0 <= chunk_index < int(upload_info["total_chunks"]):
        raise HTTPException(status_code=400, detail="Chunk number out of range")

    # This chunk may not exceed the chunk size, nor all chunks together the declared size (SEC-7)
    others = sum(b for i, b in upload_info["chunk_bytes"].items() if i != chunk_index)
    allowed = min(UPLOAD_CHUNK_SIZE, int(upload_info["total_size"]) - others)
    chunk_path = os.path.join(staging_dir, f"chunk_{chunk_index:06d}")
    written = 0
    async with aiofiles.open(chunk_path, "wb") as f_out:
        async for content in request.stream():
            if content:
                written += len(content)
                if written > allowed:
                    break
                await f_out.write(content)
    if written > allowed:
        try:
            os.remove(chunk_path)
        except OSError:
            logger.debug("fs_upload_chunk: oversized chunk already gone", exc_info=True)
        raise HTTPException(status_code=413, detail="This upload is larger than the size it announced.")

    async with _CHUNKED_UPLOADS_LOCK:
        if upload_id in _CHUNKED_UPLOADS:
            _CHUNKED_UPLOADS[upload_id]["chunks_received"].add(chunk_index)
            _CHUNKED_UPLOADS[upload_id]["chunk_bytes"][chunk_index] = written

    return {"status": "ok", "chunk_index": chunk_index}


@router.post(
    "/fs/upload/complete",
    dependencies=[Depends(require_scope("shares:manage", "shares:user_write", "storage:write", "storage:admin"))],
)
async def fs_upload_complete(
    req: UploadCompleteRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    async with _CHUNKED_UPLOADS_LOCK:
        upload_info = _CHUNKED_UPLOADS.get(req.upload_id)
        if not upload_info:
            raise HTTPException(status_code=404, detail="Upload session not found or expired")

    staging_dir = upload_info["staging_dir"]
    target_dir = upload_info["target_dir"]
    filename = upload_info["filename"]
    total_chunks = upload_info["total_chunks"]
    chunks_received = upload_info["chunks_received"]

    if len(chunks_received) < total_chunks:
        missing = set(range(total_chunks)) - chunks_received
        raise HTTPException(status_code=400, detail=f"Upload incomplete. Missing {len(missing)} chunks")
    if sum(upload_info.get("chunk_bytes", {}).values()) != int(upload_info["total_size"]):
        raise HTTPException(status_code=400, detail="The uploaded size doesn't match the announced size")

    final_target = os.path.join(target_dir, filename)
    check_user_path_access(final_target, principal, write=True)
    temp_assembly = os.path.join(target_dir, f".zettnas_tmp_{req.upload_id}_{filename}")

    sha256 = hashlib.sha256()
    try:
        async with aiofiles.open(temp_assembly, "wb") as f_out:
            for idx in range(total_chunks):
                chunk_file = os.path.join(staging_dir, f"chunk_{idx:06d}")
                if not os.path.exists(chunk_file):
                    raise HTTPException(status_code=400, detail=f"Chunk file {idx} missing on disk")
                async with aiofiles.open(chunk_file, "rb") as f_in:
                    while b := await f_in.read(65536):
                        sha256.update(b)
                        await f_out.write(b)

        computed_hash = sha256.hexdigest()
        if req.expected_sha256 and req.expected_sha256.lower().strip() != computed_hash.lower():
            if os.path.exists(temp_assembly):
                os.remove(temp_assembly)
            raise HTTPException(
                status_code=400,
                detail=f"SHA-256 integrity mismatch: expected {req.expected_sha256}, computed {computed_hash}",
            )

        os.replace(temp_assembly, final_target)
        from backend.services import upload_staging

        await asyncio.to_thread(shutil.rmtree, staging_dir, True)  # off the event loop (NARC-9)
        await asyncio.to_thread(upload_staging.forget, req.upload_id)
        async with _CHUNKED_UPLOADS_LOCK:
            _CHUNKED_UPLOADS.pop(req.upload_id, None)

        final_size = os.path.getsize(final_target)
        record_activity("upload", final_target, principal)
        add_event("success", "File Explorer", f"Completed chunked upload of {filename}")
        return {
            "status": "ok",
            "filename": filename,
            "size_bytes": final_size,
            "sha256": computed_hash,
        }
    except HTTPException:
        raise
    except Exception as e:
        if os.path.exists(temp_assembly):
            try:
                os.remove(temp_assembly)
            except Exception:
                ignored("backend.api.fs.fs_upload_complete")
        logger.error(f"[FS] Chunked assembly failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to assemble uploaded chunks: {e}") from e
