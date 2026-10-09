"""
ZettNAS Toolkit - Remote & Cloud Storage API
REST endpoints for multi-cloud integration, FUSE mounts, and backup sync.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.rclone_engine import get_rclone_engine

logger = logging.getLogger("ZettNAS.RemotesApi")

router = APIRouter(tags=["Remote Storage"])


class RemoteCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    type: str = Field(..., min_length=1, max_length=32)
    parameters: Dict[str, Any] = Field(default_factory=dict)


class RemoteMountRequest(BaseModel):
    remote_path: str = ""
    vfs_cache: str = "writes"
    read_only: bool = False


class RemoteSyncRequest(BaseModel):
    src: str = Field(..., min_length=1)
    dst: str = Field(..., min_length=1)
    action: str = Field("sync", pattern="^(sync|copy|move)$")
    dry_run: bool = False


@router.get("/remotes", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def list_cloud_remotes():
    """Lists all configured cloud and network storage remotes."""
    engine = get_rclone_engine()
    return await asyncio.to_thread(engine.list_remotes)


@router.get("/remotes/providers", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def get_storage_providers():
    """Returns curated list of cloud and network storage providers."""
    engine = get_rclone_engine()
    return engine.get_providers()


@router.post("/remotes", dependencies=[Depends(require_scope("storage:admin"))])
async def create_cloud_remote(req: RemoteCreateRequest):
    """Creates or updates a remote cloud storage backend."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(
            engine.create_remote,
            req.name,
            req.type,
            req.parameters,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/remotes/{name}", dependencies=[Depends(require_scope("storage:admin"))])
async def delete_cloud_remote(name: str):
    """Deletes a remote cloud storage backend."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.delete_remote, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/{name}/mount", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def mount_cloud_remote(name: str, req: Optional[RemoteMountRequest] = None):
    """Mounts remote cloud storage into /mnt/remotes/{name} via FUSE."""
    engine = get_rclone_engine()
    r_path = req.remote_path if req else ""
    vfs = req.vfs_cache if req else "writes"
    ro = req.read_only if req else False
    try:
        return await asyncio.to_thread(engine.mount_remote, name, r_path, vfs, ro)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/{name}/unmount", dependencies=[Depends(require_scope("storage:admin", "storage:write"))])
async def unmount_cloud_remote(name: str):
    """Unmounts /mnt/remotes/{name}."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.unmount_remote, name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/remotes/{name}/files", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def list_remote_files(name: str, path: str = ""):
    """Lists files and folders inside a remote storage location."""
    engine = get_rclone_engine()
    try:
        return await asyncio.to_thread(engine.list_remote_files, name, path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remotes/sync", dependencies=[Depends(require_scope("backup:write", "storage:write", "storage:admin"))])
async def start_remote_sync(req: RemoteSyncRequest):
    """Triggers an asynchronous cloud sync/copy/move operation."""
    engine = get_rclone_engine()
    try:
        return engine.start_sync_job(req.src, req.dst, req.action, req.dry_run)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/remotes/sync/jobs", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
async def list_sync_jobs():
    """Lists recent and active cloud sync jobs."""
    engine = get_rclone_engine()
    return engine.get_sync_jobs()
