"""A filter for the kids' devices through AdGuard Home (COMP-13): the connection and, per
family account, its devices and the services blocked for them."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope

router = APIRouter(prefix="/family-filter", tags=["Authentication & Security"])


class ConnectionIn(BaseModel):
    url: str | None = Field(default=None, max_length=200)
    user: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=256)


class PersonIn(BaseModel):
    devices: list[str] = Field(default_factory=list, max_length=32)
    blocked: list[str] = Field(default_factory=list, max_length=20)


@router.get("", dependencies=[Depends(require_scope("users:read"))])
def get_family_filter() -> dict[str, Any]:
    """The AdGuard Home connection (never its password), each filtered account's devices and
    blocked services, the family accounts that can be filtered and the services AdGuard can block."""
    from backend.services import adguard_kids
    from backend.users_db import list_users

    people = [
        {"username": u["username"], "display_name": u.get("display_name") or u["username"]}
        for u in list_users()
        if u.get("role_id") in ("kid", "share_user", "guest")  # the Kid role first of all (NSEC-12)
    ]
    return {**adguard_kids.public(), "accounts": people, "services": list(adguard_kids.SERVICES)}


@router.put("/connection", dependencies=[Depends(require_scope("users:write"))])
def put_family_filter_connection(req: ConnectionIn) -> dict[str, Any]:
    from backend.services import adguard_kids

    try:
        return adguard_kids.save_connection(**req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/check", dependencies=[Depends(require_scope("users:write"))])
def check_family_filter() -> dict[str, Any]:
    """Whether AdGuard Home answers with the saved user and password, and its version."""
    from backend.services import adguard_kids

    return adguard_kids.check()


@router.put("/people/{username}", dependencies=[Depends(require_scope("users:write"))])
def put_family_filter_person(username: str, req: PersonIn) -> dict[str, Any]:
    """Filters this account's devices in AdGuard Home; no devices stops filtering them."""
    from backend.services import adguard_kids
    from backend.users_db import list_users

    if not any(u["username"] == username for u in list_users()):
        raise HTTPException(status_code=404, detail="No such account.")
    try:
        return adguard_kids.set_person(username, req.devices, req.blocked)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except adguard_kids.AdGuardError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
