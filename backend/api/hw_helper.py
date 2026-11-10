"""The hardware helper (SEC-24 step 2): turn it on (confirmed) or off, and how it stands."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import hw_helper_container

router = APIRouter(tags=["Hardware"])


class HwHelperUpdate(BaseModel):
    enabled: bool


@router.get("/hardware/helper", dependencies=[Depends(require_scope("system:view"))])
async def get_hw_helper() -> dict[str, Any]:
    """Whether the helper runs and answers, and whether this box has the registers it serves."""
    return await asyncio.to_thread(hw_helper_container.status)


@router.put("/hardware/helper", dependencies=[Depends(require_scope("system:config"))])
async def put_hw_helper(
    req: HwHelperUpdate, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns the helper on (confirmed first: 428 until then) or off."""
    if req.enabled:
        confirm_or_raise(request, principal, "hardware.helper", hw_helper_container.CONTAINER)
    return await asyncio.to_thread(hw_helper_container.save, req.enabled)
