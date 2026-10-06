import os
import zipfile
import io
import time
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from backend.config import DATA_DIR, logger

router = APIRouter(tags=["Backup"])


@router.get("/system/backup")
async def download_backup():
    """Generates a zip archive of the configuration data directory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(DATA_DIR):
            for file in files:
                # Exclude sqlite temp files and large history db if desired. Let's exclude history.db to keep config small.
                if file in ["history.db", "history.db-shm", "history.db-wal"]:
                    continue
                # Exclude sessions so we don't leak auth state
                if file == "sessions.json":
                    continue

                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, DATA_DIR)
                z.write(file_path, rel_path)

    buf.seek(0)
    ts = time.strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=zettnas_backup_{ts}.zip"},
    )


@router.post("/system/restore")
async def restore_backup(request: Request):
    """Restores configuration from a zip archive."""

    try:
        content = await request.body()
        with zipfile.ZipFile(io.BytesIO(content), "r") as z:
            # Basic validation
            names = z.namelist()
            if any(".." in n or n.startswith("/") for n in names):
                raise HTTPException(status_code=400, detail="Invalid zip path")

            # Extract over existing files in DATA_DIR
            z.extractall(DATA_DIR)

        logger.info("Configuration restored successfully from backup.")
        return {"status": "ok", "message": "Restore successful. A reboot may be required to apply all settings."}
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip archive")
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
