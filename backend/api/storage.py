"""
ZettNAS Toolkit - Storage Subsystem API Routes
Platform Abstraction Layer (PAL) endpoints for storage pools, array topology,
and network shares (Samba/NFS/WebDAV).
"""

from typing import Any, Dict, List, Optional
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
    export_smb: bool = True
    export_nfs: bool = False
    nfs_squash: str = Field(default="no_root_squash", description="'no_root_squash', 'root_squash', or 'all_squash'")
    nfs_anonuid: int = Field(default=1000, description="Mapped UID for anonymous/squashed users")
    nfs_anongid: int = Field(default=1000, description="Mapped GID for anonymous/squashed users")
    nfs_sync: bool = Field(default=True, description="True for synchronous commits (ACID), False for async")
    nfs_clients: str = Field(default="*", description="Allowed client host, CIDR subnet, or wildcard (*)")


class StoragePoolRenameRequest(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=64, description="New name for storage pool")


class StorageSnapshotCreateRequest(BaseModel):
    subvolume: str = "@shares"
    snapshot_name: str
    readonly: bool = True
    worm_mode: Optional[str] = Field(default=None, description="Two-Tier WORM mode: 'governance' or 'compliance'")
    retention_days: Optional[int] = Field(
        default=None, ge=1, le=3650, description="WORM retention period in days (1-3650)"
    )


class StorageSnapshotBreakGlassDeleteRequest(BaseModel):
    snapshot_name: str
    reason: str = Field(
        ..., min_length=5, description="Mandatory audit justification for breaking governance WORM lock"
    )


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
            export_smb=req.export_smb,
            export_nfs=req.export_nfs,
            nfs_squash=req.nfs_squash,
            nfs_anonuid=req.nfs_anonuid,
            nfs_anongid=req.nfs_anongid,
            nfs_sync=req.nfs_sync,
            nfs_clients=req.nfs_clients,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/pools/{pool_id}/rename", dependencies=[Depends(require_scope("storage:admin"))])
def rename_storage_pool(pool_id: str, req: StoragePoolRenameRequest) -> Dict[str, Any]:
    """
    Renames an existing storage pool (OpenZFS or Btrfs) and creates an atomic
    backwards-compatibility symlink to preserve Docker container volume mounts.
    Forbidden in Observer Mode.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Storage pools and array identifiers must be managed authoritatively by the host OS.",
        )
    try:
        return adapter.rename_pool(pool_id=pool_id, new_name=req.new_name)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            worm_mode=req.worm_mode,
            retention_days=req.retention_days,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/pools/{pool_id}/snapshots/{snapshot_name}", dependencies=[Depends(require_scope("storage:admin"))])
def delete_storage_snapshot(pool_id: str, snapshot_name: str) -> Dict[str, Any]:
    """
    Deletes a Btrfs subvolume snapshot. Forbidden in Observer Mode or if WORM locked.
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


@router.post("/pools/{pool_id}/snapshots/break-glass-delete", dependencies=[Depends(require_scope("storage:admin"))])
def break_glass_delete_snapshot(pool_id: str, req: StorageSnapshotBreakGlassDeleteRequest) -> Dict[str, Any]:
    """
    Overrides Governance-mode WORM lock to delete a snapshot with mandatory audit logging.
    Forbidden for Compliance-mode WORM locks before retention expiry.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}.",
        )
    try:
        return adapter.delete_snapshot(
            pool_id=pool_id,
            snapshot_name=req.snapshot_name,
            break_glass=True,
            reason=req.reason,
        )
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
        res = adapter.restore_snapshot(
            pool_id=pool_id, snapshot_name=req.snapshot_name, target_subvol=req.target_subvol
        )
        if res.get("status") == "error":
            raise HTTPException(status_code=400, detail=res.get("message") or "Snapshot restore failed")
        return res
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))
