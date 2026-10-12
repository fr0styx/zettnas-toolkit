"""
ZettNAS Toolkit - SFTP Management REST API
Exposes status, toggles, configuration, and user permissions for inbound SFTP file sharing.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.sftp_engine import SFTPConfig, SFTPStatus, SFTPUser, get_sftp_engine

logger = logging.getLogger("ZettNAS.SFTPApi")

router = APIRouter(tags=["SFTP File Sharing"])


class SFTPToggleRequest(BaseModel):
    enabled: bool


class SFTPUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    display_name: str = ""
    password: Optional[str] = None
    pubkey: Optional[str] = None
    shares: List[str] = Field(default_factory=list)
    read_only: bool = False


@router.get("/sftp/status", response_model=SFTPStatus)
async def get_sftp_status():
    """Returns operational status, port, sidecar state, and quick-connect info for SFTP."""
    engine = get_sftp_engine()
    return await asyncio.to_thread(engine.get_status)


@router.post(
    "/sftp/toggle",
    response_model=SFTPStatus,
    dependencies=[Depends(require_scope("shares:manage", "storage:admin"))],
)
async def toggle_sftp(req: SFTPToggleRequest):
    """Enables or disables the inbound SFTP service."""
    engine = get_sftp_engine()
    if req.enabled:
        return await asyncio.to_thread(engine.start)
    else:
        return await asyncio.to_thread(engine.stop)


@router.post(
    "/sftp/config",
    dependencies=[Depends(require_scope("shares:manage", "storage:admin"))],
)
async def update_sftp_config(req: SFTPConfig):
    """Updates global SFTP configuration (port, authentication modes, chroot)."""
    engine = get_sftp_engine()
    updates = req.model_dump(exclude_unset=True)
    cfg = await asyncio.to_thread(engine.save_config, updates)
    return {"status": "ok", "config": cfg}


@router.get(
    "/sftp/users",
    dependencies=[Depends(require_scope("shares:read", "storage:admin"))],
)
async def list_sftp_users():
    """Lists configured SFTP users, authorized shares, and access levels."""
    engine = get_sftp_engine()
    users = await asyncio.to_thread(engine.list_users)
    # Mask passwords in response
    safe_users = []
    for u in users:
        item = dict(u)
        if item.get("password"):
            item["password"] = "********"
        safe_users.append(item)
    return safe_users


@router.post(
    "/sftp/users",
    dependencies=[Depends(require_scope("shares:manage", "storage:admin"))],
)
async def create_sftp_user(req: SFTPUserCreateRequest):
    """Creates a new dedicated SFTP user with designated share access."""
    engine = get_sftp_engine()
    try:
        user = await asyncio.to_thread(engine.add_user, req.model_dump())
        item = dict(user)
        if item.get("password"):
            item["password"] = "********"
        return {"status": "ok", "user": item}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[SFTP] Failed to add user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete(
    "/sftp/users/{username}",
    dependencies=[Depends(require_scope("shares:manage", "storage:admin"))],
)
async def delete_sftp_user(username: str):
    """Deletes an SFTP user and revokes their file transfer credentials."""
    engine = get_sftp_engine()
    ok = await asyncio.to_thread(engine.delete_user, username)
    if not ok:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "ok", "deleted": True}
