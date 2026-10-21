"""
ZettNAS Toolkit - Storage Subsystem API Routes
Platform Abstraction Layer (PAL) endpoints for storage pools, array topology,
and network shares (Samba/NFS/WebDAV).
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.hardware.pal_storage import (
    PlatformCapabilityError,
    get_storage_platform,
)

logger = logging.getLogger(__name__)

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


class StoragePoolExportRequest(BaseModel):
    force: bool = False


class StoragePoolImportRequest(BaseModel):
    pool_id: str
    fs_type: str = "zfs"
    target_mount: Optional[str] = None


class StorageShareCreateRequest(BaseModel):
    name: str
    path: str = ""
    comment: str = ""
    security: str = "public"
    read_only: bool = False
    export_smb: bool = True
    export_nfs: bool = False
    quota_gb: Optional[int] = Field(default=0, description="Storage quota in GB (0 = unlimited)")
    user_permissions: Optional[Dict[str, str]] = Field(
        default_factory=dict, description="User permission matrix: {username: 'rw'|'ro'|'deny'}"
    )
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


@router.get("/platform", dependencies=[Depends(require_scope("storage:read", "shares:read", "system:view"))])
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


@router.get("/pools", dependencies=[Depends(require_scope("storage:read", "system:view"))])
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


@router.get("/shares", dependencies=[Depends(require_scope("storage:read", "shares:read", "system:view"))])
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


@router.get("/overview", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_storage_overview() -> Dict[str, Any]:
    """
    Returns unified storage overview: pools, shares, platform info, and physical disk inventories.
    """
    from backend.hardware.hal import DiskDiscoveryHAL

    adapter = get_storage_platform()
    pools = adapter.list_pools()
    shares = adapter.list_shares()
    caps = adapter.get_capabilities()

    assigned_devs = set()
    for p in pools:
        for m in getattr(p, "members", []):
            name = (getattr(m, "device", "") or getattr(m, "name", "")).replace("/dev/", "")
            if name:
                assigned_devs.add(name)

    records = DiskDiscoveryHAL.discover_physical_disks()
    all_disks = []
    unassigned = []
    for r in records:
        is_assigned = r.dev_name in assigned_devs or r.role == "os"
        d_dict = {
            "dev": r.dev_name,
            "name": r.dev_name,
            "size": getattr(r, "size_formatted", getattr(r, "size_human", "0 GB")),
            "size_bytes": r.size_bytes,
            "model": r.model,
            "serial": r.serial,
            "role": r.role,
            "transport": r.transport,
            "assigned": is_assigned,
        }
        all_disks.append(d_dict)
        if not is_assigned:
            unassigned.append(d_dict)

    return {
        "platform": adapter.get_platform_type().value,
        "is_observer_mode": caps.is_observer_mode,
        "is_busy": adapter.is_storage_busy(),
        "pools": [p.model_dump() for p in pools],
        "shares": [s.model_dump() for s in shares],
        "disks": all_disks,
        "unassigned_disks": unassigned,
    }


@router.get("/disks", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_storage_disks() -> Dict[str, Any]:
    """Returns detected physical disks discovered via DiskDiscoveryHAL."""
    from backend.hardware.hal import DiskDiscoveryHAL

    records = DiskDiscoveryHAL.discover_physical_disks()
    return {
        "disks": [
            {
                "dev": r.dev_name,
                "name": r.dev_name,
                "size": getattr(r, "size_formatted", getattr(r, "size_human", "0 GB")),
                "size_bytes": r.size_bytes,
                "model": r.model,
                "serial": r.serial,
                "role": r.role,
                "transport": r.transport,
            }
            for r in records
        ]
    }


@router.post("/scrub", dependencies=[Depends(require_scope("storage:admin"))])
def trigger_storage_scrub(req: StorageScrubRequest) -> Dict[str, Any]:
    """
    Initiates or monitors non-destructive array parity check or filesystem scrub.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if not caps.can_trigger_scrub:
        raise HTTPException(
            status_code=403,
            detail=f"Storage scrub is disabled on {adapter.get_platform_type().value}.",
        )
    return adapter.trigger_scrub(pool_id=req.pool_id, action=req.action)


@router.get("/schedule", dependencies=[Depends(require_scope("storage:read"))])
def get_storage_schedule_config() -> Dict[str, Any]:
    """Retrieves current automated SMART self-test and storage scrub schedule."""
    from backend.services.scheduler import get_smart_schedule

    return get_smart_schedule()


@router.put("/schedule", dependencies=[Depends(require_scope("storage:admin"))])
def update_storage_schedule_config(req: Dict[str, Any]) -> Dict[str, Any]:
    """Updates automated SMART self-test and storage scrub schedule."""
    from backend.services.scheduler import save_smart_schedule

    return save_smart_schedule(req)


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
            quota_gb=req.quota_gb or 0,
            user_permissions=req.user_permissions or {},
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


@router.post(
    "/pools/{pool_id}/export",
    dependencies=[Depends(require_scope("storage:admin"))],
)
def export_storage_pool(pool_id: str, req: StoragePoolExportRequest = StoragePoolExportRequest()) -> Dict[str, Any]:
    """
    Gracefully flushes dirty write cache, terminates active handles,
    and exports/unmounts a storage pool for safe physical detachment.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if not caps.can_export_pools:
        raise HTTPException(
            status_code=403,
            detail=f"Pool export is disabled on {adapter.get_platform_type().value} in Observer Mode.",
        )
    try:
        return adapter.export_pool(pool_id=pool_id, force=req.force)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"[StorageAPI] Error exporting pool '{pool_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/pools/discover",
    dependencies=[Depends(require_scope("storage:admin", "storage:read"))],
)
def discover_external_storage_pools() -> Dict[str, Any]:
    """
    Discovers unimported or detachable external storage pools (e.g. USB/Thunderbolt DAS).
    """
    adapter = get_storage_platform()
    try:
        discovered = adapter.discover_external_pools()
        return {"status": "ok", "discovered_pools": discovered}
    except Exception as e:
        logger.warning(f"[StorageAPI] Error discovering external pools: {e}")
        return {"status": "ok", "discovered_pools": []}


@router.post(
    "/pools/import",
    dependencies=[Depends(require_scope("storage:admin"))],
)
def import_storage_pool(req: StoragePoolImportRequest) -> Dict[str, Any]:
    """
    Imports an external storage pool into the platform.
    """
    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if not caps.can_import_pools:
        raise HTTPException(
            status_code=403,
            detail=f"Pool import is disabled on {adapter.get_platform_type().value} in Observer Mode.",
        )
    try:
        return adapter.import_pool(pool_id=req.pool_id, fs_type=req.fs_type, target_mount=req.target_mount)
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"[StorageAPI] Error importing pool '{req.pool_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


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


@router.get("/pools/{pool_id}/snapshots", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
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


class SmartScheduleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    short_test_interval: Optional[str] = None
    short_test_day: Optional[int] = None
    short_test_hour: Optional[int] = None
    extended_test_interval: Optional[str] = None
    extended_test_day: Optional[int] = None
    extended_test_hour: Optional[int] = None
    skip_if_standby: Optional[bool] = None


@router.get("/smart/schedule", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_smart_test_schedule() -> Dict[str, Any]:
    """
    Returns current SMART test schedule, intervals, and last execution timestamps.
    """
    from backend.services.scheduler import get_smart_schedule

    return get_smart_schedule()


@router.post("/smart/schedule", dependencies=[Depends(require_scope("storage:admin"))])
def update_smart_test_schedule(req: SmartScheduleUpdateRequest) -> Dict[str, Any]:
    """
    Configures automated Short and Extended SMART test schedules.
    Preserves skip_if_standby=True invariant to never spin up sleeping drives.
    """
    from backend.services.scheduler import save_smart_schedule

    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    return save_smart_schedule(payload)


@router.get("/smart/failure-predictions", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_smart_failure_predictions() -> List[Dict[str, Any]]:
    """
    Scrutiny-style failure probability analytics and historical attribute velocity
    for all discovered storage drives.
    """
    from backend.db import query_smart_velocity
    from backend.hardware.disks import _discover_disks

    disks = _discover_disks()
    predictions = []
    for d in disks:
        dev_name = d.get("dev", "")
        if dev_name:
            v_data = query_smart_velocity(dev_name)
            v_data["model"] = d.get("model", "")
            v_data["serial"] = d.get("serial", "")
            v_data["type"] = d.get("type", "hdd")
            v_data["status"] = d.get("status", "OK")
            predictions.append(v_data)
    return predictions
