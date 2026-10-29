from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
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
    # older setup wizards sent the address as "urls"; it is folded into apprise_urls (REL-6)
    urls: list[str] = Field(default_factory=list, exclude=True)

    @model_validator(mode="after")
    def _fold_urls(self):
        for u in self.urls:
            if u and u.strip() and u.strip() not in self.apprise_urls:
                self.apprise_urls.append(u.strip())
        return self

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

    # Daily summary (Batch 6) and the weekly health report (B12a, FEAT-05)
    digest_mode: Literal["off", "daily"] = "off"
    digest_hour: int = Field(default=8, ge=0, le=23)
    weekly_report: bool = True


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
    from backend.services.ssrf_guard import validate_notification_url

    for url_val, label in [
        (req.discord_webhook_url, "Discord Webhook"),
        (req.webhook_url, "Webhook"),
        (req.ntfy_url, "ntfy"),
    ]:
        if url_val and url_val.strip() and url_val.strip() != "https://ntfy.sh":
            ok, err = validate_notification_url(url_val.strip())
            if not ok:
                raise HTTPException(status_code=400, detail=f"Invalid {label} URL: {err}")

    for u in req.apprise_urls:
        if u and u.strip():
            ok, err = validate_notification_url(u.strip())
            if not ok:
                raise HTTPException(status_code=400, detail=f"Invalid Apprise URL '{u}': {err}")

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


class MyAlertsIn(BaseModel):
    ntfy_topic: str = ""
    email: str = ""
    events: list[str] = []
    min_level: str = "warning"


@router.get("/notifications/me")
def get_my_alerts(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """This person's own alerts: where they go and which kinds (Batch 6)."""
    from backend.services.notifications import ROUTABLE_EVENTS, get_route

    return {"route": get_route(principal.username), "events": list(ROUTABLE_EVENTS)}


@router.put("/notifications/me")
def put_my_alerts(req: MyAlertsIn, principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    from backend.services.notifications import set_route

    try:
        return {"route": set_route(principal.username, req.ntfy_topic, req.email, req.events, req.min_level)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


class FrigateEventsIn(BaseModel):
    enabled: bool | None = None
    url: str | None = Field(default=None, max_length=200)
    labels: list[str] | None = Field(default=None, max_length=10)
    cameras: list[str] | None = Field(default=None, max_length=64)
    min_score: float | None = Field(default=None, ge=0, le=1)
    cooldown_min: int | None = Field(default=None, ge=1, le=240)


@router.get("/frigate", dependencies=[Depends(require_scope("system:view", "system:config"))])
def get_frigate_events() -> dict[str, Any]:
    """Frigate's detections as camera alerts (COMP-11): on or off, which objects and cameras."""
    from backend.services import frigate_events

    return {**frigate_events.public(), "choices": list(frigate_events.LABELS)}


@router.put("/frigate", dependencies=[Depends(require_scope("system:config"))])
def put_frigate_events(req: FrigateEventsIn) -> dict[str, Any]:
    from backend.services import frigate_events

    try:
        return frigate_events.save_settings(**req.model_dump(exclude_none=True))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/frigate/test", dependencies=[Depends(require_scope("system:config"))])
def test_frigate_events() -> dict[str, Any]:
    """Whether Frigate answers at the saved address, its version and its cameras."""
    from backend.services import frigate_events

    return frigate_events.check_connection()
