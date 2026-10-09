import base64
import binascii
import io
import os
import re

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image

from backend.config import MAX_WALLPAPER_BYTES, WALLPAPER_CONFIG_FILE, WALLPAPERS_DIR, logger
from backend.errors import error_response
from backend.fsutil import atomic_write_json, read_json
from backend.models.schemas import WallpaperRenameRequest, WallpaperSelectRequest

router = APIRouter(tags=["Wallpapers"])

# Extension -> served media type. Only these may be stored or served.
ALLOWED_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
# Pillow-detected format -> canonical extension (the real type wins over the name).
FORMAT_EXT = {"PNG": ".png", "JPEG": ".jpg", "GIF": ".gif", "WEBP": ".webp"}
MAX_NAME_LEN = 100


def _safe_name(name):
    """Return a sanitized basename with an allowed image extension, or None."""
    if not name or not isinstance(name, str):
        return None
    name = os.path.basename(name.replace("\\", "/"))
    if name in ("", ".", "..") or name.startswith("."):
        return None
    if os.path.splitext(name)[1].lower() not in ALLOWED_TYPES:
        return None
    return name


def _path_for(name):
    safe = _safe_name(name)
    return (safe, os.path.join(WALLPAPERS_DIR, safe)) if safe else (None, None)


def _fail(status, detail):
    return error_response(status, detail, success=False)


def _get_active():
    cfg = read_json(WALLPAPER_CONFIG_FILE, {})
    return cfg.get("active") if isinstance(cfg, dict) else None


def _set_active(name):
    atomic_write_json(WALLPAPER_CONFIG_FILE, {"active": name})


def _detect_image_format(data: bytes):
    """Validate the payload really is an image; return its canonical extension."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception:
        return None
    return FORMAT_EXT.get(fmt)


def _clean_cache_for(safe: str):
    if not safe:
        return
    cache_dir = os.path.join(WALLPAPERS_DIR, ".cache")
    for fname in [f"{safe}.webp", f"thumb_{safe}.webp"]:
        try:
            cache_path = os.path.join(cache_dir, fname)
            if os.path.isfile(cache_path):
                os.remove(cache_path)
        except Exception:
            pass


def _get_thumbnail_wallpaper_path(safe: str, wp_path: str) -> tuple[str, str]:
    ext = os.path.splitext(safe)[1].lower()
    if ext == ".gif":
        return wp_path, ALLOWED_TYPES.get(ext, "image/gif")

    cache_dir = os.path.join(os.path.dirname(wp_path), ".cache")
    thumb_path = os.path.join(cache_dir, f"thumb_{safe}.webp")

    try:
        src_mtime = os.path.getmtime(wp_path)
        if os.path.exists(thumb_path) and os.path.getmtime(thumb_path) >= src_mtime:
            return thumb_path, "image/webp"

        os.makedirs(cache_dir, exist_ok=True)
        with Image.open(wp_path) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            # Downscale thumbnail to 360x202 (16:9 standard card preview)
            im.thumbnail((360, 202), Image.Resampling.LANCZOS)
            im.save(thumb_path, "WEBP", quality=80, method=4)
        return thumb_path, "image/webp"
    except Exception as e:
        logger.warning(f"[WALLPAPER] Thumbnail fallback to original for {safe}: {e}")
        return wp_path, ALLOWED_TYPES.get(ext, "image/jpeg")


def _get_optimized_wallpaper_path(safe: str, wp_path: str) -> tuple[str, str]:
    ext = os.path.splitext(safe)[1].lower()
    if ext == ".gif":
        return wp_path, ALLOWED_TYPES.get(ext, "image/gif")

    cache_dir = os.path.join(os.path.dirname(wp_path), ".cache")
    opt_path = os.path.join(cache_dir, f"{safe}.webp")

    try:
        src_mtime = os.path.getmtime(wp_path)
        if os.path.exists(opt_path) and os.path.getmtime(opt_path) >= src_mtime:
            return opt_path, "image/webp"

        os.makedirs(cache_dir, exist_ok=True)
        with Image.open(wp_path) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            # Downscale if wider or taller than 2560x1440
            max_w, max_h = 2560, 1440
            if im.width > max_w or im.height > max_h:
                im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
            im.save(opt_path, "WEBP", quality=82, method=6)
        return opt_path, "image/webp"
    except Exception as e:
        logger.warning(f"[WALLPAPER] Optimization fallback to original for {safe}: {e}")
        return wp_path, ALLOWED_TYPES.get(ext, "image/jpeg")


@router.get("/wallpaper_url")
def get_wallpaper_url():
    active = _safe_name(_get_active())
    if active:
        safe, wp_path = _path_for(active)
        v = int(os.path.getmtime(wp_path)) if safe and os.path.isfile(wp_path) else None
        v_param = f"?v={v}" if v else ""
        return {"url": f"/api/wallpapers/download/{active}{v_param}"}
    return {"url": None}


@router.get("/wallpapers")
def list_wallpapers():
    os.makedirs(WALLPAPERS_DIR, exist_ok=True)
    files = [f for f in os.listdir(WALLPAPERS_DIR) if _safe_name(f)]
    active = _get_active()
    version = None
    if active:
        safe, wp_path = _path_for(active)
        if safe and os.path.isfile(wp_path):
            version = int(os.path.getmtime(wp_path))
    return {"files": sorted(files), "active": active, "version": version}


@router.get("/wallpapers/download/{filename}")
async def download_wallpaper(filename: str, request: Request):
    safe, wp_path = _path_for(filename)
    if not safe or not os.path.isfile(wp_path):
        return error_response(404, "Wallpaper not found.")

    accept = request.headers.get("accept", "")
    wants_webp = "image/webp" in accept
    file_sz = os.path.getsize(wp_path)

    # Deliver optimized WebP if accepted by client and original is large (> 300KB)
    if wants_webp and file_sz > 300 * 1024:
        serve_path, media_type = await run_in_threadpool(_get_optimized_wallpaper_path, safe, wp_path)
    else:
        serve_path = wp_path
        media_type = ALLOWED_TYPES.get(os.path.splitext(safe)[1].lower(), "application/octet-stream")

    return FileResponse(
        serve_path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
        },
    )


@router.get("/wallpapers/thumb/{filename}")
async def get_wallpaper_thumbnail(filename: str):
    safe, wp_path = _path_for(filename)
    if not safe or not os.path.isfile(wp_path):
        return error_response(404, "Wallpaper not found.")

    serve_path, media_type = await run_in_threadpool(_get_thumbnail_wallpaper_path, safe, wp_path)
    return FileResponse(
        serve_path,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "public, max-age=604800, stale-while-revalidate=86400",
        },
    )


@router.post("/wallpapers/upload")
async def upload_wallpaper(request: Request):
    try:
        body = await request.json()
    except Exception:
        return _fail(400, "Invalid JSON body.")

    image_data = body.get("image") if isinstance(body, dict) else None
    filename = body.get("filename", "upload.jpg") if isinstance(body, dict) else "upload.jpg"
    if not image_data or not isinstance(image_data, str):
        return _fail(400, "No image provided.")

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    # Reject oversized payloads before decoding (base64 inflates by ~4/3).
    if len(image_data) > (MAX_WALLPAPER_BYTES * 4) // 3 + 4:
        return _fail(413, f"Image exceeds {MAX_WALLPAPER_BYTES // (1024 * 1024)} MB limit.")

    try:
        binary_data = base64.b64decode(image_data, validate=False)
    except (binascii.Error, ValueError):
        return _fail(400, "Image data is not valid base64.")
    if len(binary_data) > MAX_WALLPAPER_BYTES:
        return _fail(413, f"Image exceeds {MAX_WALLPAPER_BYTES // (1024 * 1024)} MB limit.")

    ext = await run_in_threadpool(_detect_image_format, binary_data)
    if not ext:
        return _fail(415, "Unsupported file. Allowed: PNG, JPEG, GIF, WEBP.")

    # Name comes from the user, extension comes from the detected content.
    base = os.path.splitext(os.path.basename(str(filename).replace("\\", "/")))[0]
    base = re.sub(r"[^a-zA-Z0-9_-]", "_", base).strip("_")[:MAX_NAME_LEN] or "wallpaper"

    def _save_wallpaper_sync():
        os.makedirs(WALLPAPERS_DIR, exist_ok=True)
        final_name = f"{base}{ext}"
        counter = 1
        while os.path.exists(os.path.join(WALLPAPERS_DIR, final_name)):
            final_name = f"{base}_{counter}{ext}"
            counter += 1

        with open(os.path.join(WALLPAPERS_DIR, final_name), "wb") as f:
            f.write(binary_data)
        _clean_cache_for(final_name)
        _set_active(final_name)
        return final_name

    try:
        final_name = await run_in_threadpool(_save_wallpaper_sync)
    except OSError as e:
        logger.error(f"[WALLPAPER] Upload failed: {e}")
        return _fail(500, "Failed to save wallpaper.")

    return {"success": True, "url": f"/api/wallpapers/download/{final_name}", "filename": final_name}


@router.post("/wallpapers/select")
def select_wallpaper(req: WallpaperSelectRequest):
    try:
        name = req.name if req.name is not None else req.filename
        if not name:
            _set_active(None)
            return {"success": True}

        safe, wp_path = _path_for(name)
        if not safe or not os.path.isfile(wp_path):
            return _fail(404, "Wallpaper not found.")

        _set_active(safe)
        return {"success": True, "url": f"/api/wallpapers/download/{safe}"}
    except OSError as e:
        logger.error(f"[WALLPAPER] Select failed: {e}")
        return _fail(500, "Failed to select wallpaper.")


@router.post("/wallpapers/rename")
def rename_wallpaper(req: WallpaperRenameRequest):
    old_safe, old_path = _path_for(req.old_name)
    if not old_safe or not req.new_name:
        return _fail(400, "Missing or invalid parameters.")

    old_ext = os.path.splitext(old_safe)[1].lower()
    new_base = os.path.basename(str(req.new_name).replace("\\", "/"))
    if os.path.splitext(new_base)[1].lower() in ALLOWED_TYPES:
        new_base = os.path.splitext(new_base)[0]
    new_base = re.sub(r"[^a-zA-Z0-9_-]", "_", new_base).strip("_")[:MAX_NAME_LEN]
    if not new_base:
        return _fail(400, "Invalid new name.")
    # Keep the original (content-verified) extension.
    new_name = f"{new_base}{old_ext}"
    new_path = os.path.join(WALLPAPERS_DIR, new_name)

    try:
        if not os.path.isfile(old_path):
            return _fail(404, "Source file does not exist.")
        if os.path.exists(new_path) and old_path != new_path:
            return _fail(409, "A wallpaper with that name already exists.")

        os.rename(old_path, new_path)
        _clean_cache_for(old_safe)
        _clean_cache_for(new_name)
        if _get_active() == old_safe:
            _set_active(new_name)
    except OSError as e:
        logger.error(f"[WALLPAPER] Rename failed: {e}")
        return _fail(500, "Failed to rename wallpaper.")

    return {"success": True, "new_name": new_name}


@router.delete("/wallpapers/{filename}")
def delete_wallpaper(filename: str):
    safe, wp_path = _path_for(filename)
    if not safe:
        return _fail(400, "Invalid filename.")
    try:
        if os.path.isfile(wp_path):
            os.remove(wp_path)
        _clean_cache_for(safe)
        if _get_active() == safe:
            _set_active(None)
    except OSError as e:
        logger.error(f"[WALLPAPER] Delete failed: {e}")
        return _fail(500, "Failed to delete wallpaper.")
    return {"success": True}
