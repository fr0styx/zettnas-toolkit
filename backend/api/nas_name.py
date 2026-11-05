"""Find the NAS by name on the home network (NFEAT-8)."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services import nas_name

router = APIRouter(tags=["Network"])


class NasNameUpdate(BaseModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, max_length=70)


@router.get("/network/nas-name", dependencies=[Depends(require_scope("system:view"))])
async def get_nas_name() -> dict[str, Any]:
    """Whether the NAS answers to <name>.local, the name, the older names that still answer and the
    web address."""
    return await asyncio.to_thread(nas_name.status)


@router.put("/network/nas-name", dependencies=[Depends(require_scope("system:config"))])
async def put_nas_name(req: NasNameUpdate) -> dict[str, Any]:
    """Turns the name on or off or changes it; the previous name keeps answering."""
    try:
        return await asyncio.to_thread(nas_name.save, req.enabled, req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
