"""
ZettNAS Toolkit - Storage Subsystem API Routes
Platform Abstraction Layer (PAL) endpoints for storage pools, array topology,
and network shares (Samba/NFS/WebDAV).
"""

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend import config
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import require_confirmation
from backend.errors import error_response
from backend.hardware.pal_storage import (
    PlatformCapabilityError,
    get_storage_platform,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["Storage Subsystem & PAL"])


class StorageScrubRequest(BaseModel):
    # pool names go to zpool/btrfs as arguments: no leading dash, no spaces
    pool_id: str = Field("unraid_array", pattern=r"^[A-Za-z0-9_/][A-Za-z0-9_./:-]{0,127}$")
    action: str = Field("start", pattern=r"^[a-z_]{1,16}$")


class StoragePoolCreateRequest(BaseModel):
    name: str
    fs_type: str = "btrfs"
    profile: str = "raid1"
    disks: list[str] = Field(default_factory=list)
    mountpoint: str = ""
    # Formatting is irreversible (SEC-08): the user types the pool name and their password,
    # and must say so explicitly when the disks still hold data.
    confirm_name: str = ""
    current_password: str = ""
    erase_existing_data: bool = False


class StoragePoolExportRequest(BaseModel):
    force: bool = False


class StoragePoolImportRequest(BaseModel):
    pool_id: str
    fs_type: str = "zfs"
    target_mount: str | None = None


class StorageShareCreateRequest(BaseModel):
    name: str
    path: str = ""
    comment: str = ""
    security: str = "public"
    read_only: bool = False
    export_smb: bool = True
    export_nfs: bool = False
    quota_gb: int | None = Field(default=0, description="Storage quota in GB (0 = unlimited)")
    user_permissions: dict[str, str] | None = Field(
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
    worm_mode: str | None = Field(default=None, description="Two-Tier WORM mode: 'governance' or 'compliance'")
    retention_days: int | None = Field(
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
def get_storage_platform_info() -> dict[str, Any]:
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
def get_storage_pools() -> dict[str, Any]:
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
def get_storage_shares() -> dict[str, Any]:
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
def get_storage_overview() -> dict[str, Any]:
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
def get_storage_disks() -> dict[str, Any]:
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
def trigger_storage_scrub(req: StorageScrubRequest) -> dict[str, Any]:
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
def get_storage_schedule_config() -> dict[str, Any]:
    """Retrieves current automated SMART self-test and storage scrub schedule."""
    from backend.services.scheduler import get_smart_schedule

    return get_smart_schedule()


@router.put("/schedule", dependencies=[Depends(require_scope("storage:admin"))])
def update_storage_schedule_config(req: dict[str, Any]) -> dict[str, Any]:
    """Updates automated SMART self-test and storage scrub schedule."""
    from backend.services.scheduler import save_smart_schedule

    return save_smart_schedule(req)


@router.post(
    "/pools",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.pool.create"))],
)
def create_storage_pool(
    req: StoragePoolCreateRequest, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """
    Creates a new storage pool. In Observer Mode (e.g. Unraid, TrueNAS),
    this operation is strictly rejected to protect host array parity.
    """
    import re as _re

    from backend.hardware.disk_safety import check_disks
    from backend.passwords import verify_password
    from backend.users_db import get_user_by_id

    adapter = get_storage_platform()
    caps = adapter.get_capabilities()
    if caps.is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Forbidden in Observer Mode on {adapter.get_platform_type().value}. "
            "Storage pools and RAID arrays must be managed authoritatively by the host OS.",
        )
    if not _re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$", req.name or ""):
        raise HTTPException(
            status_code=400, detail="Pool name: letters, digits, - and _ (max 32), starting with a letter."
        )
    if req.fs_type.lower() not in ("btrfs", "zfs", "ext4", "xfs"):
        raise HTTPException(status_code=400, detail="Unsupported filesystem.")
    if req.confirm_name != req.name:
        raise HTTPException(status_code=400, detail="Type the pool name to confirm that the disks will be erased.")
    user = get_user_by_id(principal.user_id) if principal and principal.user_id else None
    if not user or not verify_password(req.current_password or "", user.get("password_hash", "")):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")

    mountpoint = (req.mountpoint or "").strip()
    if mountpoint:
        pool_root = os.path.realpath(getattr(config, "POOL_PATH", "") or "/mnt")
        real_mp = os.path.realpath(mountpoint)
        if not real_mp.startswith(pool_root.rstrip("/") + "/") or _re.search(r"[\x00-\x1f,]", mountpoint):
            raise HTTPException(status_code=400, detail=f"The mount point must be inside {pool_root}.")

    resolve = getattr(adapter, "_resolve_disk_path", None)
    disks = [resolve(d) if resolve else (d if d.startswith("/") else f"/dev/{d}") for d in req.disks]
    problems = check_disks(disks, allow_erase=req.erase_existing_data)
    if problems:
        return error_response(
            409,
            "These disks can't be formatted: " + "; ".join(f"{p['disk']}: {p['reason']}" for p in problems),
            error="disks_not_safe",
            problems=problems,
            erasable=all(p.get("erasable") == "true" for p in problems),
        )
    logger.warning(f"[Storage] Creating pool '{req.name}' ({req.fs_type}) on {', '.join(disks)}")
    try:
        return adapter.create_pool(
            name=req.name,
            fs_type=req.fs_type,
            profile=req.profile,
            disks=req.disks,
            mountpoint=mountpoint,
        )
    except PlatformCapabilityError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        logger.error(f"[Storage] Pool '{req.name}' was not created: {e}")
        raise HTTPException(status_code=500, detail=f"The pool was not created: {e}") from e


class ShareAccessUpdate(BaseModel):
    default_level: str = "write"
    shares: dict[str, dict[str, Any]] = Field(default_factory=dict)


@router.get("/share-access", dependencies=[Depends(require_scope("shares:manage"))])
def get_share_access() -> dict[str, Any]:
    """Who can use which share in the file manager (SEC-10)."""
    from backend.services.share_access import known_shares, load_config

    cfg = load_config()
    return {
        "default_level": cfg["default_level"],
        "levels": ["none", "read", "write"],
        "shares": [
            {"name": sh["name"], "path": sh["path"], **cfg["shares"].get(sh["name"], {"users": {}})}
            for sh in known_shares()
        ],
    }


@router.put("/share-access", dependencies=[Depends(require_scope("shares:manage"))])
def put_share_access(req: ShareAccessUpdate) -> dict[str, Any]:
    from backend.services.share_access import save_config

    try:
        return save_config(req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/shares", dependencies=[Depends(require_scope("shares:manage"))])
def create_storage_share(req: StorageShareCreateRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/pools/{pool_id}/rename", dependencies=[Depends(require_scope("storage:admin"))])
def rename_storage_pool(pool_id: str, req: StoragePoolRenameRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/pools/{pool_id}",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.pool.delete"))],
)
def delete_storage_pool(pool_id: str) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post(
    "/pools/{pool_id}/export",
    dependencies=[Depends(require_scope("storage:admin"))],
)
def export_storage_pool(pool_id: str, req: StoragePoolExportRequest = StoragePoolExportRequest()) -> dict[str, Any]:  # noqa: B008
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
        raise HTTPException(status_code=403, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[StorageAPI] Error exporting pool '{pool_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get(
    "/pools/discover",
    dependencies=[Depends(require_scope("storage:admin", "storage:read"))],
)
def discover_external_storage_pools() -> dict[str, Any]:
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
def import_storage_pool(req: StoragePoolImportRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:
        logger.error(f"[StorageAPI] Error importing pool '{req.pool_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete(
    "/shares/{name}",
    dependencies=[Depends(require_scope("shares:manage")), Depends(require_confirmation("share.delete"))],
)
def delete_storage_share(name: str) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.get("/pools/{pool_id}/snapshots", dependencies=[Depends(require_scope("storage:read", "storage:admin"))])
def list_storage_snapshots(pool_id: str) -> list[dict[str, Any]]:
    """
    Lists filesystem subvolume snapshots for a storage pool.
    """
    adapter = get_storage_platform()
    return adapter.list_snapshots(pool_id=pool_id)


@router.post("/pools/{pool_id}/snapshots", dependencies=[Depends(require_scope("storage:admin"))])
def create_storage_snapshot(pool_id: str, req: StorageSnapshotCreateRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.delete(
    "/pools/{pool_id}/snapshots/{snapshot_name}",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.snapshot.delete"))],
)
def delete_storage_snapshot(pool_id: str, snapshot_name: str) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post("/pools/{pool_id}/snapshots/break-glass-delete", dependencies=[Depends(require_scope("storage:admin"))])
def break_glass_delete_snapshot(pool_id: str, req: StorageSnapshotBreakGlassDeleteRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


@router.post(
    "/pools/{pool_id}/snapshots/restore",
    dependencies=[Depends(require_scope("storage:admin")), Depends(require_confirmation("storage.snapshot.restore"))],
)
def restore_storage_snapshot(pool_id: str, req: StorageSnapshotRestoreRequest) -> dict[str, Any]:
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
        raise HTTPException(status_code=403, detail=str(e)) from e


class SmartScheduleUpdateRequest(BaseModel):
    enabled: bool | None = None
    short_test_interval: str | None = None
    short_test_day: int | None = None
    short_test_hour: int | None = None
    extended_test_interval: str | None = None
    extended_test_day: int | None = None
    extended_test_hour: int | None = None
    skip_if_standby: bool | None = None


@router.get("/smart/schedule", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_smart_test_schedule() -> dict[str, Any]:
    """
    Returns current SMART test schedule, intervals, and last execution timestamps.
    """
    from backend.services.scheduler import get_smart_schedule

    return get_smart_schedule()


@router.post("/smart/schedule", dependencies=[Depends(require_scope("storage:admin"))])
def update_smart_test_schedule(req: SmartScheduleUpdateRequest) -> dict[str, Any]:
    """
    Configures automated Short and Extended SMART test schedules.
    Preserves skip_if_standby=True invariant to never spin up sleeping drives.
    """
    from backend.services.scheduler import save_smart_schedule

    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    return save_smart_schedule(payload)


@router.get("/smart/failure-predictions", dependencies=[Depends(require_scope("storage:read", "system:view"))])
def get_smart_failure_predictions() -> list[dict[str, Any]]:
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


@router.get("/unraid-api/status", dependencies=[Depends(require_scope("storage:read", "system:view"))])
async def unraid_api_status() -> dict[str, Any]:
    """Array, disks, shares and parity check from the Unraid API (companion mode, D5)."""
    from backend.services import unraid_api

    if not unraid_api.configured():
        raise HTTPException(status_code=404, detail="Unraid API not configured (UNRAID_API_URL, UNRAID_API_KEY)")
    try:
        return await asyncio.to_thread(unraid_api.status)
    except unraid_api.UnraidApiError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
