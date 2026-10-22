"""Ransomware guard and IP block-list endpoints (M4, M5)."""

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services import ip_block
from backend.services.ransomware_guard import get_guard

router = APIRouter(prefix="/security", tags=["Security"])


class GuardSettings(BaseModel):
    enabled: bool | None = None
    canaries: bool | None = None
    rename_delete_limit: int | None = Field(default=None, ge=3, le=100000)
    suspicious_limit: int | None = Field(default=None, ge=3, le=100000)


class BlockRequest(BaseModel):
    ip: str = Field(..., max_length=64)
    reason: str = Field(default="blocked by an admin", max_length=200)
    hours: float | None = Field(default=None, ge=0.1, le=24 * 365)


@router.get("/ransomware", dependencies=[Depends(require_scope("system:view", "audit:read"))])
def ransomware_status() -> dict[str, Any]:
    return get_guard().status()


@router.put("/ransomware", dependencies=[Depends(require_scope("system:config"))])
def ransomware_settings(req: GuardSettings) -> dict[str, Any]:
    return get_guard().update_settings(**req.model_dump())


@router.post("/ransomware/unfreeze", dependencies=[Depends(require_scope("system:config"))])
def ransomware_unfreeze(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    return get_guard().unfreeze(by=principal.username)


@router.get("/ip-blocks", dependencies=[Depends(require_scope("system:view", "audit:read"))])
def list_ip_blocks() -> list[dict[str, Any]]:
    return ip_block.list_blocks()


@router.post("/ip-blocks", dependencies=[Depends(require_scope("system:config"))])
def add_ip_block(req: BlockRequest) -> dict[str, Any]:
    try:
        ipaddress.ip_address(req.ip)
    except ValueError:
        raise HTTPException(status_code=400, detail="Not an IP address") from None
    seconds = int(req.hours * 3600) if req.hours else None
    if not ip_block.block(req.ip, req.reason, seconds=seconds):
        raise HTTPException(status_code=400, detail="Loopback and trusted addresses can't be blocked")
    return {"status": "ok"}


@router.delete("/ip-blocks/{ip}", dependencies=[Depends(require_scope("system:config"))])
def remove_ip_block(ip: str) -> dict[str, Any]:
    if not ip_block.unblock(ip):
        raise HTTPException(status_code=404, detail="Not blocked")
    return {"status": "ok"}
