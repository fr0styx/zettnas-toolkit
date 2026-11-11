"""Share links (NFEAT-2) and chosen apps (RES-6) that work from anywhere, through Tailscale Funnel."""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import settings
from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import public_apps, public_links

router = APIRouter(tags=["Network"])


class PublicLinksUpdate(BaseModel):
    enabled: bool


@router.get("/network/public-links", dependencies=[Depends(require_scope("system:view"))])
async def get_public_links(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Whether share links work from the internet, their address, and a Tailscale approval to open.
    A request that waited for the tailnet owner is only carried out for someone who may change
    settings: a read by anyone else publishes nothing (SET-02)."""
    return await asyncio.to_thread(public_links.status, principal.has_scope("system:config"))


class ClosePort(BaseModel):
    port: int = Field(default=public_links.FUNNEL_PORT, ge=1, le=65535)


@router.post("/network/public-links/close-port", dependencies=[Depends(require_scope("system:config"))])
async def close_public_port(
    req: ClosePort | None = None, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Takes the share links' port off the internet with everything it carries there, or a port
    that publishes Kiboto's own page."""
    port = req.port if req else public_links.FUNNEL_PORT
    try:
        return await asyncio.to_thread(public_links.close_port, getattr(principal, "username", "") or "", port)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.put("/network/public-links", dependencies=[Depends(require_scope("system:config"))])
async def put_public_links(
    req: PublicLinksUpdate, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Turns public share links on (confirmed first: 428 until then) or off."""
    if not req.enabled:
        return await asyncio.to_thread(public_links.disable)
    confirm_or_raise(request, principal, "network.public_links", f":{public_links.FUNNEL_PORT}")
    return await asyncio.to_thread(public_links.enable, int(settings.current("port") or 8082))


class PublicAppIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host_port: int = Field(ge=1, le=65535)
    funnel_port: int = Field(description="443 or 10000; 8443 is the share links'")


@router.get("/network/public-apps", dependencies=[Depends(require_scope("system:view"))])
async def get_public_apps() -> dict[str, Any]:
    """The apps on the internet, the Funnel ports still free and the apps that could go (RES-6)."""
    return await asyncio.to_thread(public_apps.status)


@router.post("/network/public-apps", dependencies=[Depends(require_scope("system:config"))])
async def post_public_app(
    req: PublicAppIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Puts one app's port on the internet (confirmed first: 428 until then). Never Kiboto's page."""
    confirm_or_raise(request, principal, "network.publish_app", req.name)
    actor = getattr(principal, "username", "") or ""
    try:
        return await asyncio.to_thread(public_apps.publish, req.name, req.host_port, req.funnel_port, actor)
    except public_apps.PublishError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.delete("/network/public-apps/{funnel_port}", dependencies=[Depends(require_scope("system:config"))])
async def delete_public_app(
    funnel_port: int, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Takes the app on that Funnel port off the internet."""
    try:
        return await asyncio.to_thread(public_apps.unpublish, funnel_port, getattr(principal, "username", "") or "")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e).strip("'")) from None
