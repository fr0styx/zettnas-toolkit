from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth import require_scope
from backend.services.notifications import (
    load_notification_config,
    mask_notification_config,
    save_notification_config,
    test_notification,
    test_single_channel,
)

router = APIRouter(prefix="/notifications", tags=["Notifications & Alerts"])


class NotificationConfigModel(BaseModel):
    enabled: bool = False
    unraid_notify: bool = True

    # Discord
    discord_enabled: bool = False
    discord_webhook_url: str = Field(default="", max_length=512)

    # Telegram
    telegram_enabled: bool = False
    telegram_bot_token: str = Field(default="", max_length=256)
    telegram_chat_id: str = Field(default="", max_length=128)

    # SMTP / Email
    email_enabled: bool = False
    smtp_host: str = Field(default="", max_length=256)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = Field(default="", max_length=256)
    smtp_pass: str = Field(default="", max_length=256)
    smtp_tls: bool = True
    email_from: str = Field(default="", max_length=256)
    email_to: str = Field(default="", max_length=256)

    # ntfy
    ntfy_enabled: bool = False
    ntfy_url: str = Field(default="https://ntfy.sh", max_length=256)
    ntfy_topic: str = Field(default="", max_length=128)
    ntfy_token: str = Field(default="", max_length=256)

    # Generic Webhook
    webhook_enabled: bool = False
    webhook_url: str = Field(default="", max_length=512)

    # Raw Apprise URLs
    apprise_urls: list[str] = Field(default_factory=list)

    # Event triggers
    notify_on_smart: bool = True
    notify_on_temp: bool = True
    notify_on_fan: bool = True
    notify_on_ups: bool = True
    notify_on_copy: bool = True
    notify_on_container: bool = True
    notify_on_backup: bool = True

    # Thresholds & Cooldown
    hdd_temp_threshold: int = Field(default=50, ge=30, le=80)
    cpu_temp_threshold: int = Field(default=80, ge=40, le=105)
    cooldown_seconds: int = Field(default=1800, ge=60, le=86400)


class TestChannelRequest(BaseModel):
    channel: str = Field(..., description="Channel name: discord, telegram, email, ntfy, webhook, apprise_raw, unraid")
    config: dict[str, Any] = Field(default_factory=dict, description="Configuration parameters for the channel")


@router.get("/config", dependencies=[Depends(require_scope("system:view", "system:config"))])
def get_notifications():
    """Retrieve current notification settings with sensitive credentials masked."""
    return mask_notification_config(load_notification_config())


@router.post("/config", dependencies=[Depends(require_scope("system:config"))])
def update_notifications(req: NotificationConfigModel):
    """Save notification settings, preserving existing secrets when masked."""
    data = req.model_dump()
    save_notification_config(data)
    return {"status": "ok", "config": mask_notification_config(load_notification_config())}


@router.post("/test", dependencies=[Depends(require_scope("system:config"))])
def trigger_test_notification(custom_cfg: dict[str, Any] | None = None):
    """Dispatch an immediate test alert across all configured channels."""
    res = test_notification(custom_cfg)
    return res


@router.post("/test-channel", dependencies=[Depends(require_scope("system:config"))])
def trigger_test_channel(req: TestChannelRequest):
    """Test a specific notification channel with latency telemetry and detailed diagnostic feedback."""
    return test_single_channel(req.channel, req.config)
