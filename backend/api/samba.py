"""
ZettNAS Toolkit - Samba Management API Routes
Provides REST endpoints to query and manage Samba (SMB/CIFS) service,
shares, configuration, and macOS Time Machine integration.
"""

from typing import Any, Dict, List
from fastapi import APIRouter, HTTPException, Response

from backend.services.samba_engine import (
    SambaShareConfig,
    SambaStatus,
    get_samba_engine,
)
from backend.hardware.pal_storage import (
    StoragePlatformDetector,
    PlatformType,
)

router = APIRouter(prefix="/samba", tags=["Samba File Sharing"])


@router.get("/status", response_model=SambaStatus)
def get_samba_status() -> SambaStatus:
    """Returns current runtime status of Samba service and sidecar."""
    engine = get_samba_engine()
    return engine.get_status()


@router.get("/shares", response_model=List[SambaShareConfig])
def get_samba_shares() -> List[SambaShareConfig]:
    """Returns all configured Samba shares."""
    engine = get_samba_engine()
    return engine.list_shares()


@router.post("/shares", response_model=SambaShareConfig)
def create_or_update_samba_share(share: SambaShareConfig) -> SambaShareConfig:
    """Creates or updates a Samba share."""
    platform = StoragePlatformDetector.detect()
    if platform == PlatformType.UNRAID:
        raise HTTPException(
            status_code=403,
            detail="Observer Mode active: Samba shares on Unraid must be configured in Unraid WebGUI.",
        )
    try:
        engine = get_samba_engine()
        return engine.add_or_update_share(share)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/shares/{name}")
def delete_samba_share(name: str) -> Dict[str, Any]:
    """Deletes a configured Samba share."""
    platform = StoragePlatformDetector.detect()
    if platform == PlatformType.UNRAID:
        raise HTTPException(
            status_code=403,
            detail="Observer Mode active: Modifying Unraid host shares from container is forbidden.",
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


@router.post("/reload")
def reload_samba_service() -> Dict[str, Any]:
    """Reloads Samba service configuration."""
    engine = get_samba_engine()
    success = engine.reload_service()
    return {"status": "reloaded" if success else "triggered", "success": success}
