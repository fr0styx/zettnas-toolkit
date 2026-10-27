"""One person's data: download it, or have parts of it forgotten (B8, services/user_data.py).

Anyone may export or erase their own; an administrator may for others (users:write to export,
users:delete to erase), which is how a parent handles a kid's account. Exporting someone else's
data and erasing ask for the usual confirmation, and the person is told when someone else
downloaded their data (B11, SEC-30); both are written to the security log.
"""

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal
from backend.confirmations import confirm_or_raise, require_confirmation
from backend.services import user_data

router = APIRouter(tags=["users"])


class EraseRequest(BaseModel):
    parts: list[str] = Field(default_factory=lambda: list(user_data.PARTS), max_length=len(user_data.PARTS))


def _target(user_id: str, principal: AuthenticatedPrincipal, scope: str) -> dict[str, Any]:
    from backend.users_db import get_user_by_id

    if principal.user_id != user_id and not principal.has_scope(scope):
        raise HTTPException(status_code=403, detail="You can only do this for your own account.")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


def _log(event: str, principal: AuthenticatedPrincipal, request: Request, details: dict[str, Any]) -> None:
    from backend.users_db import log_security_event

    log_security_event(
        event,
        "success",
        actor_id=principal.user_id,
        actor_username=principal.username,
        actor_ip=request.client.host if request.client else "",
        details=details,
    )


def _tell_the_person(user: dict[str, Any], principal: AuthenticatedPrincipal) -> None:
    from backend.services.notifications import notify_person

    when = time.strftime("%Y-%m-%d %H:%M")
    try:
        notify_person(
            user.get("username", ""),
            "Your data was downloaded",
            f"{principal.username} downloaded a copy of your chats, Zetty log and search data on {when}.",
        )
    except Exception:
        pass  # the security log has it either way


@router.get("/users/{user_id}/export")
def export_user_data(
    user_id: str, request: Request, principal: AuthenticatedPrincipal = Depends(get_current_principal)
) -> Response:
    user = _target(user_id, principal, "users:write")
    someone_else = principal.user_id != user_id
    if someone_else:
        confirm_or_raise(request, principal, "users.export_data", user_id)
    data = user_data.export_user(user)
    _log("user.data_exported", principal, request, {"target_user_id": user_id})
    if someone_else:
        _tell_the_person(user, principal)
    name = f"zettnas-data-{user.get('username', 'user')}-{time.strftime('%Y-%m-%d')}.json"
    return Response(
        json.dumps(data, ensure_ascii=False, indent=1, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"},
    )


@router.post("/users/{user_id}/erase-data", dependencies=[Depends(require_confirmation("users.erase_data"))])
def erase_user_data(
    user_id: str,
    req: EraseRequest,
    request: Request,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> dict[str, Any]:
    user = _target(user_id, principal, "users:delete")
    try:
        done = user_data.erase_user_data(user, tuple(req.parts))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    _log("user.data_erased", principal, request, {"target_user_id": user_id, "parts": req.parts})
    return {"status": "ok", "erased": done}
