import os
import re
import io
import base64
import binascii
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.concurrency import run_in_threadpool
from backend.config import logger, WALLPAPER_CONFIG_FILE, WALLPAPERS_DIR, MAX_WALLPAPER_BYTES
from backend.fsutil import atomic_write_json, read_json
from backend.models.schemas import WallpaperSelectRequest, WallpaperRenameRequest

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


def _get_active():
    cfg = read_json(WALLPAPER_CONFIG_FILE, {})
    return cfg.get("active") if isinstance(cfg, dict) else None


def _set_active(name):
    atomic_write_json(WALLPAPER_CONFIG_FILE, {"active": name})


def _detect_image_format(data: bytes):
    """Validate the payload really is an image; return its canonical extension."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format
            img.verify()
    except Exception:
        return None
    return FORMAT_EXT.get(fmt)


@router.get("/wallpaper_url")
async def get_wallpaper_url():
    active = _safe_name(_get_active())
    if active:
        return {"url": f"/api/wallpapers/download/{active}"}
    return {"url": None}


@router.get("/wallpapers")
async def list_wallpapers():
    os.makedirs(WALLPAPERS_DIR, exist_ok=True)
    files = [f for f in os.listdir(WALLPAPERS_DIR) if _safe_name(f)]
    return {"files": sorted(files), "active": _get_active()}


@router.get("/wallpapers/download/{filename}")
async def download_wallpaper(filename: str):
    safe, wp_path = _path_for(filename)
    if not safe or not os.path.isfile(wp_path):
        return JSONResponse(status_code=404, content={"error": "Not found"})
    media_type = ALLOWED_TYPES[os.path.splitext(safe)[1].lower()]
    return FileResponse(
        wp_path,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "max-age=3600"},
    )


@router.post("/wallpapers/upload")
async def upload_wallpaper(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid JSON body"})

    image_data = body.get("image") if isinstance(body, dict) else None
    filename = body.get("filename", "upload.jpg") if isinstance(body, dict) else "upload.jpg"
    if not image_data or not isinstance(image_data, str):
        return {"success": False, "error": "No image provided"}

    if "," in image_data:
        image_data = image_data.split(",", 1)[1]

    # Reject oversized payloads before decoding (base64 inflates by ~4/3).
    if len(image_data) > (MAX_WALLPAPER_BYTES * 4) // 3 + 4:
        return JSONResponse(status_code=413, content={"success": False, "error": f"Image exceeds {MAX_WALLPAPER_BYTES // (1024 * 1024)} MB limit"})

    try:
        binary_data = base64.b64decode(image_data, validate=False)
    except (binascii.Error, ValueError):
        return {"success": False, "error": "Image data is not valid base64"}
    if len(binary_data) > MAX_WALLPAPER_BYTES:
        return JSONResponse(status_code=413, content={"success": False, "error": f"Image exceeds {MAX_WALLPAPER_BYTES // (1024 * 1024)} MB limit"})

    ext = await run_in_threadpool(_detect_image_format, binary_data)
    if not ext:
        return JSONResponse(status_code=415, content={"success": False, "error": "Unsupported file. Allowed: PNG, JPEG, GIF, WEBP"})

    # Name comes from the user, extension comes from the detected content.
    base = os.path.splitext(os.path.basename(str(filename).replace("\\", "/")))[0]
    base = re.sub(r"[^a-zA-Z0-9_-]", "_", base).strip("_")[:MAX_NAME_LEN] or "wallpaper"

    try:
        os.makedirs(WALLPAPERS_DIR, exist_ok=True)
        final_name = f"{base}{ext}"
        counter = 1
        while os.path.exists(os.path.join(WALLPAPERS_DIR, final_name)):
            final_name = f"{base}_{counter}{ext}"
            counter += 1

        with open(os.path.join(WALLPAPERS_DIR, final_name), "wb") as f:
            f.write(binary_data)
        _set_active(final_name)
    except OSError as e:
        logger.error(f"[WALLPAPER] Upload failed: {e}")
        return {"success": False, "error": "Failed to save wallpaper"}

    return {"success": True, "url": f"/api/wallpapers/download/{final_name}", "filename": final_name}


@router.post("/wallpapers/select")
async def select_wallpaper(req: WallpaperSelectRequest):
    try:
        if not req.name:
            _set_active(None)
            return {"success": True}

        safe, wp_path = _path_for(req.name)
        if not safe or not os.path.isfile(wp_path):
            return {"success": False, "error": "File not found"}

        _set_active(safe)
        return {"success": True, "url": f"/api/wallpapers/download/{safe}"}
    except OSError as e:
        logger.error(f"[WALLPAPER] Select failed: {e}")
        return {"success": False, "error": "Failed to select wallpaper"}


@router.post("/wallpapers/rename")
async def rename_wallpaper(req: WallpaperRenameRequest):
    old_safe, old_path = _path_for(req.old_name)
    if not old_safe or not req.new_name:
        return {"success": False, "error": "Missing or invalid parameters"}

    old_ext = os.path.splitext(old_safe)[1].lower()
    new_base = os.path.basename(str(req.new_name).replace("\\", "/"))
    if os.path.splitext(new_base)[1].lower() in ALLOWED_TYPES:
        new_base = os.path.splitext(new_base)[0]
    new_base = re.sub(r"[^a-zA-Z0-9_-]", "_", new_base).strip("_")[:MAX_NAME_LEN]
    if not new_base:
        return {"success": False, "error": "Invalid new name"}
    # Keep the original (content-verified) extension.
    new_name = f"{new_base}{old_ext}"
    new_path = os.path.join(WALLPAPERS_DIR, new_name)

    try:
        if not os.path.isfile(old_path):
            return {"success": False, "error": "Source file does not exist"}
        if os.path.exists(new_path) and old_path != new_path:
            return {"success": False, "error": "Destination file already exists"}

        os.rename(old_path, new_path)
        if _get_active() == old_safe:
            _set_active(new_name)
    except OSError as e:
        logger.error(f"[WALLPAPER] Rename failed: {e}")
        return {"success": False, "error": "Failed to rename wallpaper"}

    return {"success": True, "new_name": new_name}


@router.delete("/wallpapers/{filename}")
async def delete_wallpaper(filename: str):
    safe, wp_path = _path_for(filename)
    if not safe:
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid filename"})
    try:
        if os.path.isfile(wp_path):
            os.remove(wp_path)
        if _get_active() == safe:
            _set_active(None)
    except OSError as e:
        logger.error(f"[WALLPAPER] Delete failed: {e}")
        return {"success": False, "error": "Failed to delete wallpaper"}
    return {"success": True}
