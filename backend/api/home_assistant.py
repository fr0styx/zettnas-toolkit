"""Home Assistant over MQTT discovery: the broker settings and a test send (RES-5)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services import home_assistant

router = APIRouter(prefix="/integrations/home-assistant", tags=["Integrations"])


class HomeAssistantIn(BaseModel):
    enabled: bool | None = None
    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    tls: bool | None = None
    discovery_prefix: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-/]{1,64}$")
    interval_s: int | None = Field(default=None, ge=15, le=3600)


@router.get("", dependencies=[Depends(require_scope("system:config"))])
def get_home_assistant() -> dict[str, Any]:
    """The broker settings (the password only as has_password) and how the last send went."""
    return home_assistant.public_config()


@router.put("", dependencies=[Depends(require_scope("system:config"))])
def put_home_assistant(req: HomeAssistantIn) -> dict[str, Any]:
    """Changes the settings; a password left out keeps the saved one, an empty one clears it."""
    try:
        return home_assistant.save_config(req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/test", dependencies=[Depends(require_scope("system:config"))])
def test_home_assistant() -> dict[str, Any]:
    """Announces the sensors and sends their values now, to check the broker settings."""
    cfg = home_assistant.load_config()
    if not str(cfg.get("host") or "").strip():
        raise HTTPException(status_code=400, detail="Set the broker's address first.")
    try:
        return {"ok": True, **home_assistant.publish_once(cfg)}
    except OSError as e:
        raise HTTPException(status_code=502, detail=f"The broker didn't take it: {e}") from None
