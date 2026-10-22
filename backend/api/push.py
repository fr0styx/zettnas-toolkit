"""Web Push subscription endpoints (M1)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services import web_push

router = APIRouter(prefix="/push", tags=["Push notifications"])


class SubKeys(BaseModel):
    p256dh: str = Field(..., max_length=200)
    auth: str = Field(..., max_length=100)


class Subscription(BaseModel):
    endpoint: str = Field(..., max_length=1024)
    keys: SubKeys


class Unsubscribe(BaseModel):
    endpoint: str = Field(..., max_length=1024)


@router.get("/vapid-public-key")
def vapid_public_key(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, str]:
    return {"key": web_push.public_key()}


@router.post("/subscribe")
def subscribe(req: Subscription, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    try:
        web_push.subscribe(principal.username, req.model_dump(), request.headers.get("user-agent", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "ok"}


@router.post("/unsubscribe")
def unsubscribe(req: Unsubscribe, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return {"removed": web_push.unsubscribe(req.endpoint, principal.username)}


@router.get("/devices")
def devices(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> list[dict[str, Any]]:
    return [
        {"ua": s["ua"], "created": s["created"], "endpoint_host": s["endpoint"].split("/")[2]}
        for s in web_push.subscriptions(principal.username)
    ]


@router.post("/test", dependencies=[Depends(require_scope("system:config", "users:read", "system:view"))])
def test_push(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> dict[str, Any]:
    res = web_push.notify("ZettNAS test", "Notifications reach this device.", users=[principal.username])
    if not res:
        raise HTTPException(status_code=404, detail="No device of yours has notifications turned on.")
    return {"sent": res}
