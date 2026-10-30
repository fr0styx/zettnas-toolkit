"""AI for apps (COMP-07): the OpenAI-compatible endpoint and its per-app keys.

    GET  /api/v1/ai/openai/models
    POST /api/v1/ai/openai/chat/completions   (stream: true streams server-sent events)
    POST /api/v1/ai/openai/embeddings

Apps authenticate with "Authorization: Bearer <key>", a key from POST /api/v1/ai/apps/keys
(administrators). See backend/services/ai_apps.py.
"""

import asyncio
import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import logger
from backend.services import ai_access, ai_apps

router = APIRouter(tags=["AI for apps"])


def _error(status: int, message: str, kind: str = "invalid_request_error") -> JSONResponse:
    """An error the way OpenAI clients read them."""
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": kind, "code": status}})


APP_SCOPE = [Depends(require_scope(ai_apps.SCOPE))]  # an app key, or someone who holds every scope


def _busy() -> JSONResponse:
    return _error(429, "This key already has a request running; send the next one when it is done.", "rate_limit_error")


def _slot(principal) -> str:
    return str(getattr(principal, "token_id", "") or getattr(principal, "username", "") or "-")


def _refused(principal) -> JSONResponse | None:
    if ai_access.allowed(principal):
        return None
    ai_access.log_request(principal, "apps", "", False, "refused")
    return _error(403, "AI is turned off for this key's owner. An administrator can turn it on in AI settings.")


@router.get("/ai/openai/models", dependencies=APP_SCOPE)
def openai_models(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return ai_apps.models()


@router.post("/ai/openai/chat/completions", dependencies=APP_SCOPE)
async def openai_chat(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    refused = _refused(principal)
    if refused:
        return refused
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "The body must be JSON.")
    if not isinstance(body, dict):
        return _error(400, "The body must be a JSON object.")
    try:
        ai_apps.chat_body(body, "check")
    except ValueError as e:
        return _error(400, str(e))
    t0 = time.monotonic()
    try:
        slot = ai_apps.Slot(_slot(principal))
    except ai_apps.KeyBusy:
        return _busy()
    if body.get("stream"):
        stream = ai_apps.chat_stream(body)
        try:
            first = await asyncio.to_thread(next, stream)  # errors before the first byte become 502s
        except StopIteration:
            first = b""
        except ai_apps.UpstreamError as e:
            slot.release()
            ai_access.log_request(principal, "apps", ai_apps.CHAT_MODEL, False, "failed")
            return _error(502, str(e), "server_error")
        ai_access.log_request(
            principal, "apps", ai_apps.CHAT_MODEL, False, "streamed", int((time.monotonic() - t0) * 1000)
        )

        def rest():
            try:
                yield first
                yield from stream
            finally:
                slot.release()  # the key's slot is held until the stream ends

        return StreamingResponse(rest(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
    try:
        with slot:
            data = await asyncio.to_thread(ai_apps.chat, body)
    except ai_apps.UpstreamError as e:
        ai_access.log_request(principal, "apps", ai_apps.CHAT_MODEL, False, "failed")
        return _error(502, str(e), "server_error")
    except ValueError as e:
        return _error(502, f"The chat server's answer wasn't JSON: {e}", "server_error")
    ai_access.log_request(principal, "apps", ai_apps.CHAT_MODEL, False, "answered", int((time.monotonic() - t0) * 1000))
    return data


@router.post("/ai/openai/embeddings", dependencies=APP_SCOPE)
async def openai_embeddings(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    refused = _refused(principal)
    if refused:
        return refused
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "The body must be JSON.")
    if not isinstance(body, dict):
        return _error(400, "The body must be a JSON object.")
    try:
        with ai_apps.Slot(_slot(principal)):
            return await asyncio.to_thread(ai_apps.embeddings, body)
    except ai_apps.KeyBusy:
        return _busy()
    except ValueError as e:
        return _error(400, str(e))
    except ai_apps.UpstreamError as e:
        return _error(502, str(e), "server_error")


# --- keys (administrators) --------------------------------------------------------------------


class AppKeyRequest(BaseModel):
    app: Literal["paperless", "openwebui", "homeassistant", "other"]
    name: str | None = Field(default=None, max_length=80)


def _base_url(request: Request) -> str:
    return f"{str(request.base_url).rstrip('/')}/api/v1/ai/openai"


@router.get("/ai/apps", dependencies=[Depends(require_scope("system:config"))])
def list_app_keys(request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """The apps that can be set up, and the keys made for them (masked)."""
    from backend.users_db import list_user_api_tokens

    keys = []
    for t in list_user_api_tokens(principal.user_id):
        scopes = t.get("scopes_json", t.get("scopes"))
        if isinstance(scopes, str):
            try:
                scopes = json.loads(scopes)
            except ValueError:
                scopes = []
        if scopes == [ai_apps.SCOPE]:
            keys.append(
                {
                    "id": t.get("token_id"),
                    "name": t.get("name"),
                    "masked_key": t.get("masked_token"),
                    "created": t.get("created_at"),
                    "last_used_at": t.get("last_used_at"),
                }
            )
    return {
        "base_url": _base_url(request),
        "apps": [{"app": k, "label": v["label"]} for k, v in ai_apps.APPS.items()],
        "keys": keys,
    }


@router.post("/ai/apps/keys", dependencies=[Depends(require_scope("system:config"))])
def create_app_key(
    req: AppKeyRequest, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
):
    """A key for one app, and that app's settings filled in. The key is shown this once."""
    from backend.users_db import create_scoped_api_token, log_security_event

    name = (req.name or "").strip() or f"AI for {ai_apps.APPS[req.app]['label']}"
    raw, meta = create_scoped_api_token(user_id=principal.user_id, name=name, scopes=[ai_apps.SCOPE])
    try:
        log_security_event(
            "api_token.created",
            "success",
            actor_id=principal.user_id,
            actor_username=principal.username,
            details={"name": name, "scopes": [ai_apps.SCOPE]},
        )
    except Exception:
        logger.debug("ai_apps.create_app_key: audit log failed", exc_info=True)
    return {"id": meta["token_id"], "key": raw, **ai_apps.settings_for(req.app, _base_url(request), raw)}


@router.delete("/ai/apps/keys/{token_id}", dependencies=[Depends(require_scope("system:config"))])
def delete_app_key(token_id: str, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.users_db import revoke_scoped_api_token

    if not revoke_scoped_api_token(token_id, user_id=principal.user_id):
        raise HTTPException(status_code=404, detail="No such key.")
    return {"status": "ok"}
