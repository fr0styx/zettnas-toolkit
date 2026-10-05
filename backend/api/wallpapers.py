import os
import re
import json
import base64
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from backend.config import DATA_DIR, WALLPAPER_CONFIG_FILE, WALLPAPERS_DIR
from backend.models.schemas import WallpaperSelectRequest, WallpaperRenameRequest

router = APIRouter(tags=["Wallpapers"])

@router.get("/wallpaper_url")
async def get_wallpaper_url():
    active = None
    if os.path.exists(WALLPAPER_CONFIG_FILE):
        with open(WALLPAPER_CONFIG_FILE, "r") as f:
            try:
                active = json.load(f).get("active")
            except (json.JSONDecodeError, OSError): pass
    if active:
        return {"url": f"/api/wallpapers/download/{active}"}
    return {"url": None}

@router.get("/wallpapers")
async def list_wallpapers():
    os.makedirs(WALLPAPERS_DIR, exist_ok=True)
    files = []
    for f in os.listdir(WALLPAPERS_DIR):
        if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            files.append(f)

    active = None
    if os.path.exists(WALLPAPER_CONFIG_FILE):
        with open(WALLPAPER_CONFIG_FILE, "r") as f:
            try: active = json.load(f).get("active")
            except (json.JSONDecodeError, OSError): pass

    return {"files": sorted(files), "active": active}

@router.get("/wallpapers/download/{filename}")
async def download_wallpaper(filename: str):
    wp_path = os.path.join(WALLPAPERS_DIR, filename)
    if os.path.exists(wp_path):
        return FileResponse(wp_path)
    return JSONResponse(status_code=404, content={"error": "Not found"})

@router.post("/wallpapers/upload")
async def upload_wallpaper(request: Request):
    try:
        body = await request.json()
        image_data = body.get("image")
        filename = body.get("filename", "upload.jpg")

        filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)

        if not image_data:
            return {"success": False, "error": "No image provided"}

        if "," in image_data:
            image_data = image_data.split(",")[1]

        binary_data = base64.b64decode(image_data)

        os.makedirs(WALLPAPERS_DIR, exist_ok=True)

        base, ext = os.path.splitext(filename)
        counter = 1
        final_name = filename
        while os.path.exists(os.path.join(WALLPAPERS_DIR, final_name)):
            final_name = f"{base}_{counter}{ext}"
            counter += 1

        with open(os.path.join(WALLPAPERS_DIR, final_name), "wb") as f:
            f.write(binary_data)

        with open(WALLPAPER_CONFIG_FILE, "w") as f:
            json.dump({"active": final_name}, f)

        return {"success": True, "url": f"/api/wallpapers/download/{final_name}", "filename": final_name}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/wallpapers/select")
async def select_wallpaper(req: WallpaperSelectRequest):
    try:
        filename = req.name
        if not filename:
            with open(WALLPAPER_CONFIG_FILE, "w") as f:
                json.dump({"active": None}, f)
            return {"success": True}

        wp_path = os.path.join(WALLPAPERS_DIR, filename)
        if not os.path.exists(wp_path):
            return {"success": False, "error": "File not found"}

        with open(WALLPAPER_CONFIG_FILE, "w") as f:
            json.dump({"active": filename}, f)

        return {"success": True, "url": f"/api/wallpapers/download/{filename}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/wallpapers/rename")
async def rename_wallpaper(req: WallpaperRenameRequest):
    try:
        old_name = req.old_name
        new_name = req.new_name

        if not old_name or not new_name:
            return {"success": False, "error": "Missing parameters"}

        new_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', new_name)
        if not new_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
            _, ext = os.path.splitext(old_name)
            new_name += ext

        old_path = os.path.join(WALLPAPERS_DIR, old_name)
        new_path = os.path.join(WALLPAPERS_DIR, new_name)

        if not os.path.exists(old_path):
            return {"success": False, "error": "Source file does not exist"}

        if os.path.exists(new_path) and old_path != new_path:
            return {"success": False, "error": "Destination file already exists"}

        os.rename(old_path, new_path)

        active = None
        if os.path.exists(WALLPAPER_CONFIG_FILE):
            with open(WALLPAPER_CONFIG_FILE, "r") as f:
                try: active = json.load(f).get("active")
                except (json.JSONDecodeError, OSError): pass
        if active == old_name:
            with open(WALLPAPER_CONFIG_FILE, "w") as f:
                json.dump({"active": new_name}, f)

        return {"success": True, "new_name": new_name}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.delete("/wallpapers/{filename}")
async def delete_wallpaper(filename: str):
    try:
        wp_path = os.path.join(WALLPAPERS_DIR, filename)
        if os.path.exists(wp_path):
            os.remove(wp_path)

        active = None
        if os.path.exists(WALLPAPER_CONFIG_FILE):
            with open(WALLPAPER_CONFIG_FILE, "r") as f:
                try: active = json.load(f).get("active")
                except (json.JSONDecodeError, OSError): pass
        if active == filename:
            with open(WALLPAPER_CONFIG_FILE, "w") as f:
                json.dump({"active": None}, f)

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}
