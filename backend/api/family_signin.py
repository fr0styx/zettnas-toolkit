"""One family sign-in for the apps (NFEAT-6): Pocket ID run and filled by Kiboto."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.confirmations import confirm_or_raise
from backend.services import family_signin

router = APIRouter(tags=["Users"])


def _actor(principal: AuthenticatedPrincipal) -> str:
    return getattr(principal, "username", "") or ""


def _bad(e: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(e))


@router.get("/family-signin", dependencies=[Depends(require_scope("users:read"))])
async def get_family_signin() -> dict[str, Any]:
    """Whether Pocket ID runs, its address, how many people it knows and which apps can sign in with it."""
    return await asyncio.to_thread(family_signin.status)


class EnabledIn(BaseModel):
    enabled: bool


@router.put("/family-signin", dependencies=[Depends(require_scope("users:write"))])
async def put_family_signin(
    req: EnabledIn, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Starts Pocket ID (confirmed first: 428 until then) or stops it; its data and passkeys stay."""
    try:
        if not req.enabled:
            return await asyncio.to_thread(family_signin.disable, _actor(principal))
        confirm_or_raise(request, principal, "users.family_signin", family_signin.CONTAINER)
        return await asyncio.to_thread(family_signin.enable, _actor(principal))
    except family_signin.SignInError as e:
        raise _bad(e) from None


@router.post("/family-signin/sync", dependencies=[Depends(require_scope("users:write"))])
async def post_family_signin_sync(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    """Brings Pocket ID's people in step with Kiboto's users now (it also happens on turning it on)."""
    try:
        return await asyncio.to_thread(family_signin.sync, _actor(principal))
    except family_signin.SignInError as e:
        raise _bad(e) from None


@router.post("/family-signin/users/{user_id}/link", dependencies=[Depends(require_scope("users:write"))])
async def post_family_signin_link(
    user_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """A link that signs this person in to Pocket ID once (24 hours), so they can add a passkey."""
    try:
        return await asyncio.to_thread(family_signin.sign_in_link, user_id, _actor(principal))
    except family_signin.SignInError as e:
        raise _bad(e) from None


@router.post("/family-signin/apps/{app}", dependencies=[Depends(require_scope("users:write"))])
async def post_family_signin_app(
    app: str, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Lets the family sign in to that app with Pocket ID (confirmed first): the issuer, client ID and the
    secret, shown this once, to paste into the app."""
    if app not in family_signin.APPS:
        raise HTTPException(status_code=404, detail="Kiboto has no sign-in preset for that app.")
    confirm_or_raise(request, principal, "users.family_signin_app", family_signin.APPS[app]["name"])
    try:
        return await asyncio.to_thread(family_signin.connect_app, app, _actor(principal))
    except family_signin.SignInError as e:
        raise _bad(e) from None


@router.delete("/family-signin/apps/{app}", dependencies=[Depends(require_scope("users:write"))])
async def delete_family_signin_app(
    app: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> dict[str, Any]:
    """Removes the app's client from Pocket ID; the app's own sign-in settings stay until changed there."""
    try:
        return await asyncio.to_thread(family_signin.disconnect_app, app, _actor(principal))
    except KeyError:
        raise HTTPException(status_code=404, detail="That app isn't connected.") from None
