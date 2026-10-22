"""
ZettNAS Toolkit - Samba Management API Routes
Provides REST endpoints to query and manage Samba (SMB/CIFS) service,
shares, configuration, and macOS Time Machine integration.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.auth import require_scope
from backend.confirmations import require_confirmation
from backend.hardware.pal_storage import (
    PlatformType,
    StoragePlatformDetector,
    get_storage_platform,
)
from backend.services.samba_engine import (
    SambaShareConfig,
    SambaStatus,
    get_samba_engine,
)

router = APIRouter(prefix="/samba", tags=["Samba File Sharing"])


@router.get("/status", response_model=SambaStatus)
def get_samba_status() -> SambaStatus:
    """Returns current runtime status of Samba service and sidecar."""
    engine = get_samba_engine()
    return engine.get_status()


@router.get("/shares", response_model=list[SambaShareConfig])
def get_samba_shares() -> list[SambaShareConfig]:
    """Returns all configured Samba shares."""
    engine = get_samba_engine()
    return engine.list_shares()


@router.post("/shares", response_model=SambaShareConfig, dependencies=[Depends(require_scope("shares:manage"))])
def create_or_update_samba_share(share: SambaShareConfig) -> SambaShareConfig:
    """Creates or updates a Samba share."""
    pal = get_storage_platform()
    if pal.get_capabilities().is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Observer Mode active: Samba shares on {pal.get_platform_type().value} must be configured in host OS.",
        )
    try:
        engine = get_samba_engine()
        return engine.add_or_update_share(share)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete(
    "/shares/{name}",
    dependencies=[Depends(require_scope("shares:manage")), Depends(require_confirmation("share.delete"))],
)
def delete_samba_share(name: str) -> dict[str, Any]:
    """Deletes a configured Samba share."""
    pal = get_storage_platform()
    if pal.get_capabilities().is_observer_mode:
        raise HTTPException(
            status_code=403,
            detail=f"Observer Mode active: Modifying host shares on {pal.get_platform_type().value} from container is forbidden.",
        )
    engine = get_samba_engine()
    if engine.remove_share(name):
        return {"status": "deleted", "name": name}
    raise HTTPException(status_code=404, detail=f"Share '{name}' not found")


@router.get("/config")
def get_samba_config() -> Response:
    """Returns current smb.conf text."""
    engine = get_samba_engine()
    conf_text = engine.get_config_text()
    return Response(content=conf_text, media_type="text/plain")


@router.post("/reload", dependencies=[Depends(require_scope("shares:manage"))])
def reload_samba_service() -> dict[str, Any]:
    """Reloads Samba service configuration."""
    engine = get_samba_engine()
    success = engine.reload_service()
    return {"status": "reloaded" if success else "triggered", "success": success}
