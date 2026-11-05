"""Share links that work from anywhere, through Tailscale Funnel (NFEAT-2)."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend import settings
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import public_links

router = APIRouter(tags=["Network"])


class PublicLinksUpdate(BaseModel):
    enabled: bool


@router.get("/network/public-links", dependencies=[Depends(require_scope("system:view"))])
async def get_public_links() -> dict[str, Any]:
    """Whether share links work from the internet, their address, and a Tailscale approval to open."""
    return await asyncio.to_thread(public_links.status)


@router.put("/network/public-links", dependencies=[Depends(require_scope("system:config"))])
async def put_public_links(
    req: PublicLinksUpdate, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns public share links on (confirmed first: 428 until then) or off."""
    if not req.enabled:
        return await asyncio.to_thread(public_links.disable)
    confirm_or_raise(request, principal, "network.public_links", f":{public_links.FUNNEL_PORT}")
    return await asyncio.to_thread(public_links.enable, int(settings.current("port") or 8082))
