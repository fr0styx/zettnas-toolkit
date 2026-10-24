import asyncio
import os
import tempfile
import time
import zipfile
from typing import Any, Optional

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.config import CLIENT_PREFS_FILE, logger
from backend.confirmations import require_confirmation
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.pal_storage import PlatformCapabilityError, get_storage_platform
from backend.paging import PageParams
from backend.services.backup_engine import (
    delete_backup_job,
    execute_backup_job,
    generate_backup_zip_stream,
    get_backup_history,
    get_backup_jobs,
    restore_backup_archive,
    save_backup_job,
)
from backend.services.broadcaster import broadcaster
from backend.state import Z_STATE

router = APIRouter(tags=["Backup"])


# -------------------------------------------------------------------------
# Pydantic Schemas for Hyper-Backup & Snapshots
# -------------------------------------------------------------------------


class BackupJobModel(BaseModel):
    id: str | None = None
    name: str = Field(..., description="Human-readable job name")
    source_pool: str = Field("default", description="Storage pool ID")
    source_subvolume: str = Field("", description="Subvolume or share name to backup (data jobs)")
    kind: str = Field("data", description="'data' (a pool folder) or 'config' (ZettNAS settings, encrypted)")
    local_path: str | None = Field("", description="Folder in the pool for settings backups")
    destination_type: str = Field("remote", description="'remote', 'local_snapshot' or (settings) 'local_folder'")
    remote_name: str | None = Field("", description="Configured Rclone remote name")
    remote_path: str | None = Field("", description="Remote bucket or directory path")
    schedule: str = Field("daily", description="'hourly', 'daily', 'weekly', or 'manual'")
    retention_count: int = Field(7, description="Number of historical snapshots to retain")
    enabled: bool = Field(True, description="Whether scheduled execution is active")
    encrypted: bool = Field(False, description="Enable client-side rclone crypt encryption")
    encryption_password: str | None = Field(None, description="Password for client-side encryption")


class SnapshotCreateModel(BaseModel):
    pool_id: str = "default"
    subvol_name: str
    snapshot_name: str | None = None
    readonly: bool = True


class SnapshotRestoreModel(BaseModel):
    pool_id: str = "default"
    snapshot_name: str
    target_subvol: str | None = ""


# -------------------------------------------------------------------------
# Client Preferences
# -------------------------------------------------------------------------


@router.get("/system/client-preferences")
def get_client_preferences():
    """Returns persistent client UI preferences (themes, widgets, window layouts) from DATA_DIR."""
    prefs = read_json(CLIENT_PREFS_FILE, default={})
    return {"status": "ok", "preferences": prefs}


@router.post(
    "/system/client-preferences",
    # One file shared by every user's browser, so only admins write it; other users keep
    # their settings in their own browser.
    dependencies=[Depends(require_scope("system:config"))],
)
async def save_client_preferences(request: Request):
    """Persists client UI preferences into DATA_DIR so they are preserved in backups and cross-device sync."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from None
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


# -------------------------------------------------------------------------
# Configuration Zip Archives (Export / Import)
# -------------------------------------------------------------------------


class ConfigBackupRequest(BaseModel):
    passphrase: str = ""


def _backup_response(passphrase: str = "") -> StreamingResponse:
    buf = generate_backup_zip_stream(passphrase=passphrase)
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = f"zettnas_backup_{ts}.zettbak" if passphrase else f"zettnas_backup_{ts}.zip"
    return StreamingResponse(
        buf,
        media_type="application/octet-stream" if passphrase else "application/zip",
        headers={"Content-Disposition": f"attachment; filename={name}"},
    )


@router.get("/system/backup", dependencies=[Depends(require_scope("*"))])
def download_backup():
    """Configuration backup as a plain zip (users, settings, shares, stacks, VM definitions)."""
    return _backup_response()


@router.post("/system/backup", dependencies=[Depends(require_scope("*"))])
def download_encrypted_backup(req: ConfigBackupRequest):
    """Configuration backup, encrypted with the given passphrase (AES-256-GCM, scrypt)."""
    if req.passphrase and len(req.passphrase) < 8:
        raise HTTPException(status_code=400, detail="Use a passphrase of at least 8 characters.")
    return _backup_response(req.passphrase)


def _safe_restore_archive(path: str, passphrase: str = "") -> dict:
    with open(path, "rb") as archive_file:
        return restore_backup_archive(archive_file, passphrase=passphrase)


@router.post(
    "/system/restore", dependencies=[Depends(require_scope("*")), Depends(require_confirmation("system.restore"))]
)
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

        result = await asyncio.to_thread(
            _safe_restore_archive, tmp_path, request.headers.get("x-backup-passphrase", "")
        )
        client_prefs = await asyncio.to_thread(read_json, CLIENT_PREFS_FILE, {})

        return {
            "status": "ok",
            "message": "Restore complete. Restart ZettNAS to apply everything; you will need to sign in again.",
            "restored_files": (result or {}).get("restored"),
            "client_preferences": client_prefs,
        }
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip archive") from None
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"[BACKUP] Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# -------------------------------------------------------------------------
# Hyper-Backup Jobs & 3-2-1 Pipelines
# -------------------------------------------------------------------------


@router.get("/backup/schedule", dependencies=[Depends(require_scope("backup:read", "backup:manage", "system:config"))])
def list_backup_jobs():
    """Lists all scheduled hyper-backup jobs."""
    # Passphrases never leave the server
    jobs = [
        {**j, "encryption_password": None, "has_passphrase": bool(j.get("encryption_password"))}
        for j in get_backup_jobs()
    ]
    return {"status": "ok", "jobs": jobs}


@router.post(
    "/backup/schedule", dependencies=[Depends(require_scope("backup:write", "backup:manage", "system:config"))]
)
def create_or_update_backup_job(job: BackupJobModel):
    """Creates or updates a scheduled hyper-backup job."""
    try:
        saved = save_backup_job(job.model_dump() if hasattr(job, "model_dump") else job.dict())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "status": "ok",
        "job": {**saved, "encryption_password": None, "has_passphrase": bool(saved.get("encryption_password"))},
    }


@router.delete(
    "/backup/schedule/{job_id}", dependencies=[Depends(require_scope("backup:write", "backup:manage", "system:config"))]
)
def remove_backup_job(job_id: str):
    """Deletes a scheduled hyper-backup job."""
    success = delete_backup_job(job_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {"status": "ok", "message": f"Job '{job_id}' deleted."}


@router.post(
    "/backup/schedule/{job_id}/run",
    dependencies=[Depends(require_scope("backup:write", "backup:manage", "system:config"))],
)
async def trigger_backup_job(job_id: str):
    """Triggers immediate execution of a hyper-backup job in the background."""
    try:
        result = await asyncio.to_thread(execute_backup_job, job_id)
        return {"status": "ok", "result": result}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"[HYPER-BACKUP] Manual execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/backup/history", dependencies=[Depends(require_scope("backup:read", "backup:manage", "system:config"))])
def list_backup_history(page: PageParams = Depends()):
    """Retrieves recent execution history for backup pipelines."""
    rows = get_backup_history(limit=page.fetch)
    return {"status": "ok", "history": page.slice(rows), **page.meta(len(rows))}


# -------------------------------------------------------------------------
# Storage Pool Snapshots & Rollback
# -------------------------------------------------------------------------


@router.get(
    "/backup/snapshots",
    dependencies=[Depends(require_scope("backup:read", "backup:manage", "system:config", "storage:read"))],
)
def list_pool_snapshots(pool_id: str = "default"):
    """Lists filesystem snapshots for a storage pool."""
    pal = get_storage_platform()
    try:
        snaps = pal.list_snapshots(pool_id=pool_id)
        return {"status": "ok", "pool_id": pool_id, "snapshots": snaps}
    except Exception as e:
        logger.error(f"[SNAPSHOTS] Failed to list snapshots for pool {pool_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/backup/snapshots",
    dependencies=[Depends(require_scope("backup:write", "backup:manage", "system:config", "storage:admin"))],
)
def create_pool_snapshot(req: SnapshotCreateModel):
    """Creates an atomic filesystem snapshot on the storage platform."""
    pal = get_storage_platform()
    snap_name = req.snapshot_name or f"{req.subvol_name}_{time.strftime('%Y%m%d_%H%M%S')}"
    try:
        res = pal.create_snapshot(
            pool_id=req.pool_id,
            subvol_name=req.subvol_name,
            snapshot_name=snap_name,
            readonly=req.readonly,
        )
        return {"status": "ok", "result": res}
    except PlatformCapabilityError as pce:
        raise HTTPException(status_code=400, detail=str(pce)) from pce
    except Exception as e:
        logger.error(f"[SNAPSHOTS] Failed to create snapshot {snap_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post(
    "/backup/restore-snapshot",
    dependencies=[Depends(require_scope("backup:write", "backup:manage", "system:config", "storage:admin"))],
)
def restore_pool_snapshot(req: SnapshotRestoreModel):
    """Restores or rolls back an atomic filesystem snapshot."""
    pal = get_storage_platform()
    try:
        res = pal.restore_snapshot(
            pool_id=req.pool_id,
            snapshot_name=req.snapshot_name,
            target_subvol=req.target_subvol or "",
        )
        if res.get("status") == "error":
            raise HTTPException(status_code=400, detail=res.get("message") or "Snapshot restore failed")
        return {"status": "ok", "result": res}
    except PlatformCapabilityError as pce:
        raise HTTPException(status_code=400, detail=str(pce)) from pce
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[SNAPSHOTS] Failed to restore snapshot {req.snapshot_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/backup/snapshots/{pool_id}/{snapshot_name}",
    dependencies=[
        Depends(require_scope("backup:write", "backup:manage", "system:config", "storage:admin")),
        Depends(require_confirmation("storage.snapshot.delete")),
    ],
)
def delete_pool_snapshot(pool_id: str, snapshot_name: str):
    """Deletes an atomic filesystem snapshot."""
    pal = get_storage_platform()
    try:
        res = pal.delete_snapshot(pool_id=pool_id, snapshot_name=snapshot_name)
        return {"status": "ok", "result": res}
    except PlatformCapabilityError as pce:
        raise HTTPException(status_code=400, detail=str(pce)) from pce
    except Exception as e:
        logger.error(f"[SNAPSHOTS] Failed to delete snapshot {snapshot_name}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# -------------------------------------------------------------------------
# Application & Appdata Backups (Features 21a, 21b, 21c)
# -------------------------------------------------------------------------


class AppBackupRequest(BaseModel):
    reason: str = Field("on-demand", description="'on-demand', 'uninstall', or 'scheduled'")
    custom_name: str | None = Field(None, description="Optional custom name for the backup archive")


class AppRestoreRequest(BaseModel):
    recreate_container: bool = Field(True, description="Whether to recreate the container after restoring appdata")
    target_mount_overrides: dict[str, str] | None = Field(
        None, description="Optional mapping of source -> new destination path"
    )


@router.post(
    "/docker/containers/{container_id}/backup",
    dependencies=[Depends(require_scope("containers:manage", "backup:write", "backup:manage"))],
)
async def backup_container_app(container_id: str, req: AppBackupRequest | None = None):
    """Takes an on-demand backup of an installed container app's data and synthesized compose config."""
    from backend.services.app_backup import create_app_backup

    reason = req.reason if req else "on-demand"
    custom_name = req.custom_name if req else None
    try:
        record = await asyncio.to_thread(create_app_backup, container_id, reason=reason, custom_name=custom_name)
        return {"status": "ok", "backup": record}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"[App Backup] Failed to backup container {container_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/backup/apps",
    dependencies=[Depends(require_scope("backup:read", "backup:manage", "containers:read"))],
)
async def list_app_backups_endpoint(app_name: str | None = None):
    """Lists saved app data & configuration archives, optionally filtered by app name."""
    from backend.services.app_backup import list_app_backups

    try:
        backups = await asyncio.to_thread(list_app_backups, app_name)
        return {"status": "ok", "backups": backups}
    except Exception as e:
        logger.error(f"[App Backup] Failed to list app backups: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/backup/apps/{backup_id}/download",
    dependencies=[Depends(require_scope("backup:read", "backup:manage"))],
)
async def download_app_backup(backup_id: str):
    """Downloads an application backup archive (.tar.gz)."""
    from backend.services.app_backup import get_app_backup_path

    filepath = await asyncio.to_thread(get_app_backup_path, backup_id)
    if not filepath or not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"Backup archive '{backup_id}' not found.")
    filename = os.path.basename(filepath)

    def iter_file():
        with open(filepath, "rb") as f:
            while chunk := f.read(65536):
                yield chunk

    return StreamingResponse(
        iter_file(),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/backup/apps/{backup_id}/restore",
    dependencies=[Depends(require_scope("containers:manage", "backup:write", "backup:manage"))],
)
async def restore_app_backup_endpoint(backup_id: str, req: AppRestoreRequest | None = None):
    """Restores application configuration and appdata from a backup archive."""
    from backend.services.app_backup import restore_app_backup

    recreate = req.recreate_container if req else True
    overrides = req.target_mount_overrides if req else None
    try:
        res = await asyncio.to_thread(
            restore_app_backup,
            backup_id,
            recreate_container=recreate,
            target_mount_overrides=overrides,
        )
        return {"status": "ok", "result": res}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve)) from ve
    except Exception as e:
        logger.error(f"[App Backup] Failed to restore backup {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/backup/apps/{backup_id}",
    dependencies=[
        Depends(require_scope("containers:manage", "backup:write", "backup:manage")),
        Depends(require_confirmation("backup.delete")),
    ],
)
async def delete_app_backup_endpoint(backup_id: str):
    """Deletes an application backup archive from disk and registry."""
    from backend.services.app_backup import delete_app_backup

    try:
        success = await asyncio.to_thread(delete_app_backup, backup_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Backup archive '{backup_id}' not found.")
        return {"status": "ok", "message": f"Backup '{backup_id}' deleted."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[App Backup] Failed to delete backup {backup_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
