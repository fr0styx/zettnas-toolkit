"""Kiboto boxes that know each other (RES-9, COMP-14): the owner's routes and the ones paired boxes call."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.rate_limit import rate_limit
from backend.services import fleet, fleet_buddy

router = APIRouter(tags=["Fleet"])


def _actor(principal: AuthenticatedPrincipal) -> str:
    return getattr(principal, "username", "") or ""


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.get("/fleet", dependencies=[Depends(require_scope("system:view"))])
async def get_fleet() -> dict[str, Any]:
    """This box, a waiting pairing code, and each paired box with its summary (asked at most once a minute)."""
    return await asyncio.to_thread(fleet.status, True)


@router.post("/fleet/pairing", dependencies=[Depends(require_scope("system:config"))])
async def post_pairing(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """A pairing code (10 minutes, single use) for another box to type in, with this box's address."""
    try:
        return await asyncio.to_thread(fleet.new_code, _actor(principal))
    except fleet.FleetError as e:
        raise _bad(e) from None


class PairIn(BaseModel):
    address: str = Field(min_length=8, max_length=255)
    code: str = Field(min_length=16, max_length=32)


@router.post("/fleet/peers", dependencies=[Depends(require_scope("system:config"))])
async def post_peer(
    req: PairIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Pairs with the box at that address using its code (confirmed first: 428 until then)."""
    confirm_or_raise(request, principal, "fleet.pair", req.address)
    try:
        return await asyncio.to_thread(fleet.pair_with, req.address, req.code, _actor(principal))
    except fleet.FleetError as e:
        raise _bad(e) from None


@router.delete("/fleet/peers/{box_id}", dependencies=[Depends(require_scope("system:config"))])
async def delete_peer(
    box_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Unpairs; the other box is told and forgets this one too. Backups already there stay."""
    try:
        return await asyncio.to_thread(fleet.forget, box_id, _actor(principal))
    except KeyError:
        raise HTTPException(status_code=404, detail="No paired box with that id.") from None


class OfferIn(BaseModel):
    enabled: bool


@router.put("/fleet/peers/{box_id}/offer", dependencies=[Depends(require_scope("system:config"))])
async def put_offer(
    box_id: str, req: OfferIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Lets that box back up here (confirmed first when turned on) or stops new space being given."""
    if not _known(box_id):
        raise HTTPException(status_code=404, detail="No paired box with that id.")
    if req.enabled:
        confirm_or_raise(request, principal, "fleet.offer_space", str(fleet.peer(box_id).get("name") or ""))
    return await asyncio.to_thread(fleet.set_offer, box_id, req.enabled, _actor(principal))


def _known(box_id: str) -> bool:
    try:
        fleet.peer(box_id)
    except KeyError:
        return False
    return True


class BuddyIn(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=64)


@router.post("/fleet/peers/{box_id}/backup", dependencies=[Depends(require_scope("system:config"))])
async def post_buddy_backup(
    box_id: str, req: BuddyIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Asks that box for backup space and sets up an off-site backup of these folders there."""
    if not _known(box_id):
        raise HTTPException(status_code=404, detail="No paired box with that id.")
    try:
        return await asyncio.to_thread(fleet_buddy.back_up_to, box_id, req.paths, _actor(principal))
    except fleet.FleetError as e:
        raise _bad(e) from None


# ---- called by paired boxes over the tailnet (their token, or the pairing code, is the credential) ----


class PeerPairIn(BaseModel):
    code: str = Field(min_length=16, max_length=32)
    box_id: str = Field(min_length=16, max_length=16)
    name: str = Field(default="", max_length=64)
    address: str = Field(min_length=8, max_length=255)
    token: str = Field(min_length=32, max_length=64)


@router.post("/fleet/peer/pair", dependencies=[Depends(rate_limit("fleet.pair", 10, 600, per="ip"))])
async def peer_pair(req: PeerPairIn) -> dict[str, Any]:
    """Another box pairs with this one, using the pairing code shown here."""
    try:
        return await asyncio.to_thread(fleet.accept_pairing, req.code, req.box_id, req.name, req.address, req.token)
    except fleet.FleetError as e:
        raise HTTPException(status_code=403, detail=str(e)) from None


def _peer(request: Request) -> str:
    box_id = fleet.peer_for_token(request.headers.get("authorization", ""))
    if not box_id:
        raise HTTPException(status_code=401, detail="Not a paired box.")
    return box_id


@router.get("/fleet/peer/summary", dependencies=[Depends(rate_limit("fleet.peer", 120, 60, per="ip"))])
async def peer_summary(request: Request) -> dict[str, Any]:
    """This box's summary for a paired box: name, version, storage, backups."""
    _peer(request)
    return await asyncio.to_thread(fleet.summary)


@router.post("/fleet/peer/buddy", dependencies=[Depends(rate_limit("fleet.peer", 120, 60, per="ip"))])
async def peer_buddy(request: Request) -> dict[str, Any]:
    """A paired box asks for backup space; given only when this box's owner allowed it."""
    box_id = _peer(request)
    try:
        return await asyncio.to_thread(fleet_buddy.give_space, box_id)
    except fleet.FleetError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None


@router.post("/fleet/peer/unpair", dependencies=[Depends(rate_limit("fleet.peer", 120, 60, per="ip"))])
async def peer_unpair(request: Request) -> dict[str, Any]:
    """A paired box unpaired: this one forgets it too."""
    box_id = _peer(request)
    await asyncio.to_thread(fleet.forget, box_id, "", False)
    return {"ok": True}
