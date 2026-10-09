"""
ZettNAS Toolkit - Storage Subsystem API Routes
Platform Abstraction Layer (PAL) endpoints for storage pools, array topology,
and network shares (Samba/NFS/WebDAV).
"""

from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.hardware.pal_storage import (
    PlatformCapabilityError,
    get_storage_platform,
)

router = APIRouter(prefix="/storage", tags=["Storage Subsystem & PAL"])


class StorageScrubRequest(BaseModel):
    pool_id: str = "unraid_array"
    action: str = "start"


class StoragePoolCreateRequest(BaseModel):
    name: str
    fs_type: str = "btrfs"
    profile: str = "raid1"
    disks: List[str] = Field(default_factory=list)
    mountpoint: str = ""


class StorageShareCreateRequest(BaseModel):
    name: str
    path: str = ""
    comment: str = ""
    security: str = "public"
    read_only: bool = False


class StorageSnapshotCreateRequest(BaseModel):
    subvolume: str = "@shares"
    snapshot_name: str
    readonly: bool = True


class StorageSnapshotRestoreRequest(BaseModel):
    snapshot_name: str
    target_subvol: str = ""


@router.get("/platform")
def get_storage_platform_info() -> Dict[str, Any]:
    """
    Returns platform classification (Unraid, TrueNAS, Generic Linux),
    capabilities (observer mode vs active provisioner), and storage busy state.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    return {
        "platform": adapter.get_platform_type().value,
        "capabilities": caps.model_dump(),
        "is_busy": adapter.is_storage_busy(),
    }


@router.get("/pools")
def get_storage_pools() -> Dict[str, Any]:
    """
    Returns hierarchical storage pool and array topology, including parity protection,
    data disks, SSD cache tiers, capacity gauges, and health statuses.
    """
    adapter = get_storage_platform()
    pools = adapter.list_pools()
    return {
        "platform": adapter.get_platform_type().value,
        "is_observer_mode": adapter.get_capabilities().is_observer_mode,
        "is_busy": adapter.is_storage_busy(),
        "pools": [p.model_dump() for p in pools],
    }


@router.get("/shares")
def get_storage_shares() -> Dict[str, Any]:
    """
    Returns network shares (Samba, NFS, WebDAV) with comment, security level,
    cache tiering settings, and live disk usage statistics.
    """
    adapter = get_storage_platform()
    shares = adapter.list_shares()
    return {
        "platform": adapter.get_platform_type().value,
        "is_observer_mode": adapter.get_capabilities().is_observer_mode,
        "shares": [s.model_dump() for s in shares],
    }


@router.post("/scrub", dependencies=[Depends(require_scope("storage:admin"))])
def trigger_storage_scrub(req: StorageScrubRequest) -> Dict[str, Any]:
    """
    Initiates or monitors non-destructive array parity check or filesystem scrub.
    """
    adapter = get_storage_platform()
    return adapter.trigger_scrub(pool_id=req.pool_id, action=req.action)


@router.post("/pools", dependencies=[Depends(require_scope("storage:admin"))])
def create_storage_pool(req: StoragePoolCreateRequest) -> Dict[str, Any]:
    """
    Creates a new storage pool. In Observer Mode (e.g. Unraid, TrueNAS),
    this operation is strictly rejected to protect host array parity.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Storage pools and RAID arrays must be managed authoritatively by the host OS.",
        )
    try:
        return adapter.create_pool(
            name=req.name,
            fs_type=req.fs_type,
            profile=req.profile,
            disks=req.disks,
            mountpoint=req.mountpoint,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/shares", dependencies=[Depends(require_scope("shares:manage"))])
def create_storage_share(req: StorageShareCreateRequest) -> Dict[str, Any]:
    """
    Creates a new network share. In Observer Mode (e.g. Unraid, TrueNAS),
    shares must be created via the host WebGUI or configuration files.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Network shares must be configured via host OS to ensure proper Samba driver integration.",
        )
    try:
        return adapter.create_share(
            name=req.name,
            path=req.path,
            comment=req.comment,
            security=req.security,
            read_only=req.read_only,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/pools/{pool_id}", dependencies=[Depends(require_scope("storage:admin"))])
def delete_storage_pool(pool_id: str) -> Dict[str, Any]:
    """
    Destroys/unmounts a storage pool. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.destroy_pool(pool_id=pool_id)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/shares/{name}", dependencies=[Depends(require_scope("shares:manage"))])
def delete_storage_share(name: str) -> Dict[str, Any]:
    """
    Deletes a network share configuration. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.delete_share(name=name)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/pools/{pool_id}/snapshots")
def list_storage_snapshots(pool_id: str) -> List[Dict[str, Any]]:
    """
    Lists filesystem subvolume snapshots for a storage pool.
    """
    adapter = get_storage_platform()
    return adapter.list_snapshots(pool_id=pool_id)


@router.post("/pools/{pool_id}/snapshots", dependencies=[Depends(require_scope("storage:admin"))])
def create_storage_snapshot(pool_id: str, req: StorageSnapshotCreateRequest) -> Dict[str, Any]:
    """
    Creates an atomic Btrfs subvolume snapshot. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.create_snapshot(
            pool_id=pool_id,
            subvol_name=req.subvolume,
            snapshot_name=req.snapshot_name,
            readonly=req.readonly,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/pools/{pool_id}/snapshots/{snapshot_name}", dependencies=[Depends(require_scope("storage:admin"))])
def delete_storage_snapshot(pool_id: str, snapshot_name: str) -> Dict[str, Any]:
    """
    Deletes a Btrfs subvolume snapshot. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.delete_snapshot(pool_id=pool_id, snapshot_name=snapshot_name)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/pools/{pool_id}/snapshots/restore", dependencies=[Depends(require_scope("storage:admin"))])
def restore_storage_snapshot(pool_id: str, req: StorageSnapshotRestoreRequest) -> Dict[str, Any]:
    """
    Restores or rolls back a Btrfs subvolume snapshot. Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        res = adapter.restore_snapshot(pool_id=pool_id, snapshot_name=req.snapshot_name, target_subvol=req.target_subvol)
        if res.get("status") == "error":
            raise HTTPException(status_code=400, detail=res.get("message") or "Snapshot restore failed")
        return res
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))
