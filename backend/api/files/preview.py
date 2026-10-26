"""Previews, image thumbnails, media info, streaming and zip downloads.

Part of backend/api/fs.py, split out by ARC-5."""

import asyncio
import hashlib
import mimetypes
import os
import tempfile
import time
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from backend.api.files.common import _contained, _user_file_headers
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.fsutil import prune_protected, resolve_within
from backend.logging_config import sanitize_string
from backend.services import media_info, thumbs, video_compat
from backend.services.path_access import ALLOWED_BROWSE_ROOTS, check_user_path_access

router = APIRouter()


def _extract_image_metadata(file_path: str) -> dict:
    """Size, color and EXIF details for the viewer's info panel (backend/services/photo_meta.py)."""
    from backend.services.photo_meta import extract_image_metadata

    return extract_image_metadata(file_path)


@router.get("/fs/preview", dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))])
async def fs_preview(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Universal Quick Look preview generator.
    Redacts sensitive credentials from config/text files. Generates 1KB hex dumps for binaries.
    """
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot preview a directory")

    filename = os.path.basename(target)
    ext = os.path.splitext(filename)[1].lower()
    sz = os.path.getsize(target)

    # 1. Image formats
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff", ".heic", ".heif"}
    if ext in image_exts:
        is_heif = ext in {".heic", ".heif"}
        preview_url = f"/api/fs/preview/image?path={target}" if is_heif else f"/api/fs/download?path={target}"
        result = {
            "status": "ok",
            "type": "image",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "url": preview_url,
            "download_url": f"/api/fs/download?path={target}",
        }
        img_meta = _extract_image_metadata(target)
        result.update(img_meta)
        return result

    # 2. Media (audio / video) formats
    media_exts = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"}
    if ext in media_exts:
        return {
            "status": "ok",
            "type": "media",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "stream_url": f"/api/fs/stream?path={target}",
        }

    # 3. PDF
    if ext == ".pdf":
        return {
            "status": "ok",
            "type": "pdf",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "url": f"/api/fs/download?path={target}",
        }

    # 4. Text / Code / Config formats
    text_exts = {
        ".txt",
        ".md",
        ".json",
        ".js",
        ".mjs",
        ".ts",
        ".html",
        ".css",
        ".py",
        ".sh",
        ".yaml",
        ".yml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".xml",
        ".csv",
        ".log",
        ".toml",
        ".sql",
        ".c",
        ".h",
        ".cpp",
        ".rs",
        ".go",
        ".dockerfile",
    }

    def _make_hex_dump(raw_bytes: bytes) -> list[str]:
        lines = []
        for i in range(0, len(raw_bytes), 16):
            chunk = raw_bytes[i : i + 16]
            hex_part = " ".join(f"{b:02x}" for b in chunk)
            ascii_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            lines.append(f"{i:08x}  {hex_part:<48}  |{ascii_part}|")
        return lines

    def _read_preview_bytes(file_path: str, count: int) -> bytes:
        with open(file_path, "rb") as f:
            return f.read(count)

    if ext in text_exts or filename.startswith(".") or sz <= 1024 * 1024:
        try:
            head = await asyncio.to_thread(_read_preview_bytes, target, 65536)
            if b"\x00" not in head:
                text_content = head.decode("utf-8", errors="replace")
                sanitized = sanitize_string(text_content)
                lines = sanitized.splitlines()
                return {
                    "status": "ok",
                    "type": "text",
                    "path": target,
                    "name": filename,
                    "size": sz,
                    "ext": ext,
                    "content": sanitized,
                    "lines_count": len(lines),
                    "truncated": sz > 65536,
                }
        except Exception as e:
            logger.warning(f"[PREVIEW] Text read error for {target}: {e}")

    # 5. Binary Hex Preview (1KB)
    try:
        sample = await asyncio.to_thread(_read_preview_bytes, target, 1024)
        dump = _make_hex_dump(sample)
        return {
            "status": "ok",
            "type": "hex",
            "path": target,
            "name": filename,
            "size": sz,
            "ext": ext,
            "hex_dump": dump,
        }
    except Exception as e:
        logger.error(f"[PREVIEW] Hex dump error for {target}: {e}")
        raise HTTPException(status_code=500, detail="Unable to generate preview") from e


@router.get(
    "/fs/preview/image",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
async def fs_preview_image(
    path: str,
    thumb: int | None = None,
    max_dim: int | None = None,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Thumbnails and screen-sized previews as WebP: photos (including Apple HEIC/HEIF) and
    video frames, cached on disk (backend/services/thumbs.py). Other files are served as they are.
    """
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot preview a directory")

    ext = os.path.splitext(target)[1].lower()
    is_heif = ext in {".heic", ".heif"}
    if not thumb and not max_dim and not is_heif:
        return FileResponse(target, headers=_user_file_headers(mimetypes.guess_type(target)[0]))

    kind = thumbs.kind(target)
    if kind is None:
        if ext in {".svg", ".ico"}:
            return FileResponse(target, headers=_user_file_headers(mimetypes.guess_type(target)[0]))
        raise HTTPException(status_code=415, detail="No preview for this file type")

    limit = thumbs.THUMB_SIZE if thumb else (min(max_dim, thumbs.MAX_SIZE) if max_dim else 2560)
    data = await asyncio.to_thread(thumbs.get, target, limit)
    if data is None:
        if kind == "image" and not is_heif:
            return FileResponse(target, headers=_user_file_headers(mimetypes.guess_type(target)[0]))
        raise HTTPException(status_code=415, detail="This file can't be previewed")
    mtime = os.path.getmtime(target)
    etag = f'"{hashlib.md5(f"{target}:{mtime}:{limit}".encode()).hexdigest()}"'
    return Response(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=86400, stale-while-revalidate=3600", "ETag": etag},
    )


@router.get(
    "/fs/media/info",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
async def fs_media_info(path: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """Duration, resolution, codecs, frame rate and rotation of a video or audio file."""
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Not a file")
    info = await asyncio.to_thread(media_info.probe, target)
    if info is None:
        raise HTTPException(status_code=415, detail="Not a video or audio file")
    return info


@router.get(
    "/fs/stream/compat",
    dependencies=[Depends(require_scope("shares:read", "storage:read", "system:view"))],
)
def fs_stream_compat(
    path: str,
    start: float = 0.0,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """The video converted to H.264/AAC in fragmented MP4 while it plays, from `start` seconds."""
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target) or thumbs.kind(target) != "video":
        raise HTTPException(status_code=415, detail="Not a video file")
    try:
        chunks, _stop = video_compat.stream(target, max(0.0, min(start, 7 * 24 * 3600)))
    except video_compat.Busy as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return StreamingResponse(
        iterate_in_threadpool(chunks),
        media_type="video/mp4",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/fs/stream")
def fs_stream(
    path: str,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """HTTP 206 Partial Content Range streaming for video and audio playback."""
    check_user_path_access(path, principal)
    target = _contained(path, must_exist=True)
    if os.path.isdir(target):
        raise HTTPException(status_code=400, detail="Cannot stream a directory")

    file_size = os.path.getsize(target)
    range_header = request.headers.get("range")

    import mimetypes

    content_type, _ = mimetypes.guess_type(target)
    if not content_type:
        content_type = "application/octet-stream"

    if not range_header:

        def iter_full():
            with open(target, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iter_full(),
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                **_user_file_headers(content_type),
            },
        )

    range_str = range_header.replace("bytes=", "").strip()
    range_parts = range_str.split("-")
    try:
        start = int(range_parts[0]) if range_parts[0] else 0
        end = int(range_parts[1]) if len(range_parts) > 1 and range_parts[1] else file_size - 1
    except ValueError:
        raise HTTPException(status_code=416, detail="Invalid range request") from None

    start = max(0, start)
    end = min(file_size - 1, end)
    if start > end or start >= file_size:
        raise HTTPException(
            status_code=416,
            detail="Requested range not satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_length = end - start + 1

    def iter_range():
        with open(target, "rb") as f:
            f.seek(start)
            remaining = chunk_length
            while remaining > 0:
                read_sz = min(remaining, 65536)
                data = f.read(read_sz)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_length),
            **_user_file_headers(content_type),
        },
    )


@router.get("/fs/download-zip")
def fs_download_zip(
    paths: str,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Streams a zip archive containing multiple selected files or folders without staging on disk."""
    path_list = [p.strip() for p in paths.split(",") if p.strip()]
    if not path_list:
        raise HTTPException(status_code=400, detail="No paths specified")

    for p in path_list:
        check_user_path_access(p, principal)
        target = _contained(p, must_exist=True)
        if resolve_within(target, ALLOWED_BROWSE_ROOTS) is None:
            raise HTTPException(status_code=403, detail="Path outside allowed folders")

    def _zip_generator():
        spool = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)  # noqa: SIM115
        try:
            with zipfile.ZipFile(spool, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for p in path_list:
                    real_target = _contained(p, must_exist=True)
                    base = os.path.basename(real_target)
                    if os.path.isdir(real_target):
                        for root_dir, sub_dirs, files in os.walk(real_target):
                            prune_protected(root_dir, sub_dirs)
                            for f in files:
                                fp = os.path.join(root_dir, f)
                                # Ensure symlinks inside directories do not escape allowed roots or user bounds
                                if os.path.islink(fp):
                                    resolved_sym = os.path.realpath(fp)
                                    if resolve_within(resolved_sym, ALLOWED_BROWSE_ROOTS) is None:
                                        continue
                                    try:
                                        check_user_path_access(resolved_sym, principal)
                                    except HTTPException:
                                        continue
                                rel = os.path.relpath(fp, os.path.dirname(real_target))
                                zf.write(fp, arcname=rel)
                    else:
                        if os.path.islink(real_target):
                            resolved_sym = os.path.realpath(real_target)
                            if resolve_within(resolved_sym, ALLOWED_BROWSE_ROOTS) is None:
                                continue
                            try:
                                check_user_path_access(resolved_sym, principal)
                            except HTTPException:
                                continue
                        zf.write(real_target, arcname=base)
            spool.seek(0)
            while chunk := spool.read(65536):
                yield chunk
        finally:
            spool.close()

    ts = int(time.time())
    zip_name = f"download_{ts}.zip"
    return StreamingResponse(
        _zip_generator(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )
