import tempfile
import time
import zipfile

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.config import logger
from backend.services.backup_engine import generate_backup_zip_stream, restore_backup_archive

router = APIRouter(tags=["Backup"])


@router.get("/system/backup")
def download_backup():
    """Generates a zip archive of the configuration data directory."""
    buf = generate_backup_zip_stream()
    ts = time.strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=zettnas_backup_{ts}.zip"},
    )


@router.post("/system/restore")
async def restore_backup(request: Request):
    """Restores configuration from a zip archive."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
            tmp_path = tmp.name
            async for chunk in request.stream():
                if chunk:
                    tmp.write(chunk)

        with open(tmp_path, "rb") as archive_file:
            restore_backup_archive(archive_file)

        return {"status": "ok", "message": "Restore successful. A reboot may be required to apply all settings."}
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
