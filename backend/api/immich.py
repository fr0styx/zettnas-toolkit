"""Immich: where it runs, each person's connection, and thumbnails for search results (Batch 6)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.services import immich_photos as im

router = APIRouter(tags=["Immich"])


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=300)


class KeyIn(BaseModel):
    api_key: str = Field(min_length=20, max_length=200)


@router.get("/immich")
def get_status(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return im.status(principal.username)


@router.put("/immich/url", dependencies=[Depends(require_scope("system:config", "ai:manage"))])
def put_url(req: UrlIn):
    try:
        return {"url": im.set_url(req.url)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.put("/immich/me")
def connect_me(req: KeyIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    try:
        return im.connect(principal.username, req.api_key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except im.ImmichError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None


@router.delete("/immich/me")
def disconnect_me(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return {"disconnected": im.disconnect(principal.username)}


@router.get("/immich/thumbnail/{asset_id}", dependencies=[Depends(require_scope("shares:read", "system:read"))])
def get_thumbnail(asset_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    try:
        data, ctype = im.thumbnail(principal.username, asset_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except im.ImmichError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=3600"})
