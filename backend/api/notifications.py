from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.services.notifications import (
    load_notification_config,
    save_notification_config,
    test_notification,
)

router = APIRouter(prefix="/notifications", tags=["Notifications & Alerts"])


class NotificationConfigModel(BaseModel):
    enabled: bool = False
    unraid_notify: bool = True
    ntfy_enabled: bool = False
    ntfy_url: str = Field(default="https://ntfy.sh", max_length=256)
    ntfy_topic: str = Field(default="", max_length=128)
    ntfy_token: str = Field(default="", max_length=256)
    webhook_enabled: bool = False
    webhook_url: str = Field(default="", max_length=512)
    notify_on_smart: bool = True
    notify_on_temp: bool = True
    notify_on_fan: bool = True
    notify_on_copy: bool = True
    hdd_temp_threshold: int = Field(default=50, ge=30, le=80)
    cpu_temp_threshold: int = Field(default=80, ge=40, le=105)
    cooldown_seconds: int = Field(default=1800, ge=60, le=86400)


@router.get("/config")
async def get_notifications():
    return load_notification_config()


@router.post("/config")
async def update_notifications(req: NotificationConfigModel):
    data = req.model_dump()
    save_notification_config(data)
    return {"status": "ok", "config": load_notification_config()}


@router.post("/test")
async def trigger_test_notification(custom_cfg: dict[str, Any] | None = None):
    res = test_notification(custom_cfg)
    return res
