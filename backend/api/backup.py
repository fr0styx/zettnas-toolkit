import asyncio
import aiofiles
import tempfile
import time
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.auth import require_scope
from backend.config import CLIENT_PREFS_FILE, logger
from backend.fsutil import atomic_write_json, read_json
from backend.services.backup_engine import generate_backup_zip_stream, restore_backup_archive
from backend.services.broadcaster import broadcaster
from backend.state import Z_STATE

router = APIRouter(tags=["Backup"])


@router.get("/system/client-preferences")
def get_client_preferences():
    """Returns persistent client UI preferences (themes, widgets, window layouts) from DATA_DIR."""
    prefs = read_json(CLIENT_PREFS_FILE, default={})
    return {"status": "ok", "preferences": prefs}


@router.post("/system/client-preferences")
async def save_client_preferences(request: Request):
    """Persists client UI preferences into DATA_DIR so they are preserved in backups and cross-device sync."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Preferences must be a JSON dictionary")

    current = await asyncio.to_thread(read_json, CLIENT_PREFS_FILE, {})
    current.update(data)
    await asyncio.to_thread(atomic_write_json, CLIENT_PREFS_FILE, current)

    with Z_STATE.lock:
        Z_STATE.client_preferences = current
        if Z_STATE.cached_stats:
            Z_STATE.cached_stats["client_preferences"] = current
            broadcaster.broadcast(Z_STATE.cached_stats, full_data=Z_STATE.cached_stats)

    return {"status": "ok", "message": "Client preferences saved", "preferences": current}


@router.get("/system/backup", dependencies=[Depends(require_scope("backup:read", "backup:manage", "system:config"))])
def download_backup():
    """Generates a zip archive of the configuration data directory."""
    buf = generate_backup_zip_stream()
    ts = time.strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=zettnas_backup_{ts}.zip"},
    )


def _safe_restore_archive(path: str) -> None:
    with open(path, "rb") as archive_file:
        restore_backup_archive(archive_file)


@router.post("/system/restore", dependencies=[Depends(require_scope("backup:write", "backup:manage", "system:config"))])
async def restore_backup(request: Request):
    """Restores configuration from a zip archive."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp_path = tmp.name

        async with aiofiles.open(tmp_path, "wb") as f_out:
            async for chunk in request.stream():
                if chunk:
                    await f_out.write(chunk)

        await asyncio.to_thread(_safe_restore_archive, tmp_path)
        client_prefs = await asyncio.to_thread(read_json, CLIENT_PREFS_FILE, {})

        return {
            "status": "ok",
            "message": "Restore successful. A reboot or page refresh may be required to apply all settings.",
            "client_preferences": client_prefs,
        }
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip archive")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"[BACKUP] Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path:
            import os

            try:
                os.remove(tmp_path)
            except OSError:
                pass
