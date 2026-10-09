import json
import os
import subprocess
import time
import urllib.parse
from typing import Any

import apprise
import httpx

_http_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.Client(
            timeout=8.0,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            follow_redirects=True,
        )
    return _http_client


def close_notification_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        try:
            _http_client.close()
        except Exception:
            pass
        _http_client = None


from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "notifications.json")

MASK_PLACEHOLDER = "********"
SECRET_FIELDS = {"smtp_pass", "telegram_bot_token", "ntfy_token"}

DEFAULT_NOTIFICATION_CONFIG: dict[str, Any] = {
    "enabled": False,
    # Host fallback
    "unraid_notify": True,
    # Discord
    "discord_enabled": False,
    "discord_webhook_url": "",
    # Telegram
    "telegram_enabled": False,
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    # Email / SMTP
    "email_enabled": False,
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_pass": "",
    "smtp_tls": True,
    "email_from": "",
    "email_to": "",
    # ntfy
    "ntfy_enabled": False,
    "ntfy_url": "https://ntfy.sh",
    "ntfy_topic": "",
    "ntfy_token": "",
    # Generic Webhook
    "webhook_enabled": False,
    "webhook_url": "",
    # Apprise Raw URLs
    "apprise_urls": [],
    # Event triggers
    "notify_on_smart": True,
    "notify_on_temp": True,
    "notify_on_fan": True,
    "notify_on_ups": True,
    "notify_on_copy": True,
    "notify_on_container": True,
    "notify_on_backup": True,
    # Thresholds
    "hdd_temp_threshold": 50,
    "cpu_temp_threshold": 80,
    # Cooldown in seconds per event key (30 minutes default)
    "cooldown_seconds": 1800,
}

# Alert tracking for deduplication: key -> {"last_sent": float, "last_level": str}
_alert_history: dict[str, dict[str, Any]] = {}


def load_notification_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_NOTIFICATION_CONFIG)
    loaded = read_json(NOTIFICATIONS_FILE, {})
    if isinstance(loaded, dict):
        cfg.update(loaded)
    return cfg


def mask_notification_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the notification config with secrets masked for safe UI display."""
    masked = dict(cfg)
    for field in SECRET_FIELDS:
        if masked.get(field):
            masked[field] = MASK_PLACEHOLDER
    return masked


def unmask_notification_config(new_cfg: dict[str, Any], existing_cfg: dict[str, Any]) -> dict[str, Any]:
    """Restore existing secret values if the caller sent back the MASK_PLACEHOLDER."""
    resolved = dict(new_cfg)
    for field in SECRET_FIELDS:
        if resolved.get(field) == MASK_PLACEHOLDER:
            resolved[field] = existing_cfg.get(field, "")
    return resolved


def save_notification_config(cfg: dict[str, Any]) -> None:
    existing = load_notification_config()
    merged = unmask_notification_config(cfg, existing)
    atomic_write_json(NOTIFICATIONS_FILE, merged)


def build_apprise_urls(cfg: dict[str, Any]) -> list[str]:
    """Synthesize structured channel credentials into standard Apprise URL schemas."""
    urls: list[str] = []

    # 1. Discord
    if cfg.get("discord_enabled") and cfg.get("discord_webhook_url"):
        d_url = cfg.get("discord_webhook_url", "").strip()
        if d_url:
            urls.append(d_url)

    # 2. Telegram: tgram://{bot_token}/{chat_id}
    if cfg.get("telegram_enabled"):
        token = cfg.get("telegram_bot_token", "").strip()
        chat_id = cfg.get("telegram_chat_id", "").strip()
        if token and chat_id:
            # Ensure chat_id has leading '-' or numbers preserved
            urls.append(f"tgram://{token}/{chat_id}")

    # 3. Email / SMTP: mailto://user:pass@host:port?to=recipients&from=sender
    if cfg.get("email_enabled") and cfg.get("smtp_host"):
        host = cfg.get("smtp_host", "").strip()
        port = cfg.get("smtp_port", 587)
        user = urllib.parse.quote_plus(cfg.get("smtp_user", "").strip())
        pwd = urllib.parse.quote_plus(cfg.get("smtp_pass", "").strip())
        auth = f"{user}:{pwd}@" if user and pwd else (f"{user}@" if user else "")
        proto = "mailtos" if cfg.get("smtp_tls", True) else "mailto"
        to_addr = cfg.get("email_to", "").strip()
        from_addr = cfg.get("email_from", "").strip()

        params = []
        if to_addr:
            params.append(f"to={urllib.parse.quote_plus(to_addr)}")
        if from_addr:
            params.append(f"from={urllib.parse.quote_plus(from_addr)}")

        query = f"?{'&'.join(params)}" if params else ""
        urls.append(f"{proto}://{auth}{host}:{port}{query}")

    # 4. ntfy: ntfys://host/topic or ntfy://host/topic
    if cfg.get("ntfy_enabled") and cfg.get("ntfy_topic"):
        topic = cfg.get("ntfy_topic", "").strip()
        base_url = (
            cfg.get("ntfy_url", "https://ntfy.sh")
            .rstrip("/")
            .replace("https://", "ntfys://")
            .replace("http://", "ntfy://")
        )
        token = cfg.get("ntfy_token", "").strip()
        token_param = f"?token={token}" if token else ""
        urls.append(f"{base_url}/{topic}{token_param}")

    # 5. Generic Webhook
    if cfg.get("webhook_enabled") and cfg.get("webhook_url"):
        wb = cfg.get("webhook_url", "").strip()
        if wb:
            urls.append(wb)

    # 6. Raw Apprise URLs
    raw_urls = cfg.get("apprise_urls", [])
    if isinstance(raw_urls, str):
        raw_urls = [raw_urls]
    for r in raw_urls:
        if isinstance(r, str) and r.strip():
            urls.append(r.strip())

    return urls


def _find_unraid_notify() -> str | None:
    candidates = [
        "/usr/local/emhttp/webGui/scripts/notify",
        "/host/usr/local/emhttp/webGui/scripts/notify",
    ]
    for c in candidates:
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


def _dispatch_unraid(script: str, title: str, message: str, level: str) -> bool:
    unraid_level = "normal"
    if level in ("warning", "warn"):
        unraid_level = "warning"
    elif level in ("critical", "alert", "error"):
        unraid_level = "alert"

    try:
        subprocess.run(
            [script, "-e", "ZettNAS", "-s", title, "-d", message, "-i", unraid_level],
            check=False,
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception as e:
        logger.warning(f"[NOTIFY] Unraid notify failed: {e}")
        return False


def _dispatch_ntfy(cfg: dict[str, Any], title: str, message: str, level: str) -> bool:
    topic = cfg.get("ntfy_topic", "").strip()
    if not topic:
        return False

    base_url = cfg.get("ntfy_url", "https://ntfy.sh").rstrip("/")
    url = f"{base_url}/{topic}"

    priority_map = {
        "normal": "3",
        "info": "3",
        "warning": "4",
        "warn": "4",
        "critical": "5",
        "alert": "5",
        "error": "5",
    }
    priority = priority_map.get(level, "3")

    tags_map = {
        "normal": "information_source",
        "info": "information_source",
        "warning": "warning",
        "warn": "warning",
        "critical": "rotating_light,skull",
        "alert": "rotating_light",
        "error": "x",
    }
    tags = tags_map.get(level, "bell")

    headers = {
        "Title": title,
        "Priority": priority,
        "Tags": tags,
    }
    token = cfg.get("ntfy_token", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        client = get_http_client()
        resp = client.post(url, content=message.encode("utf-8"), headers=headers)
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        logger.warning(f"[NOTIFY] ntfy push failed: {e}")
        return False


def _dispatch_webhook(cfg: dict[str, Any], title: str, message: str, level: str) -> bool:
    url = cfg.get("webhook_url", "").strip()
    if not url:
        return False

    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        color_map = {
            "normal": 0x25C2A0,
            "info": 0x25C2A0,
            "warning": 0xF59E0B,
            "warn": 0xF59E0B,
            "critical": 0xEF4444,
            "alert": 0xEF4444,
            "error": 0xEF4444,
        }
        color = color_map.get(level, 0x25C2A0)
        payload = {
            "username": "ZettNAS",
            "embeds": [
                {
                    "title": title,
                    "description": message,
                    "color": color,
                    "footer": {"text": "ZettNAS Hardware Suite"},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            ],
        }
    else:
        payload = {
            "event": "zettnas_alert",
            "title": title,
            "message": message,
            "level": level,
            "timestamp": time.time(),
        }

    try:
        client = get_http_client()
        resp = client.post(url, json=payload)
        return resp.status_code in (200, 201, 204)
    except Exception as e:
        logger.warning(f"[NOTIFY] Webhook POST failed: {e}")
        return False


def _dispatch_apprise(cfg: dict[str, Any], title: str, message: str, level: str) -> bool:
    urls = build_apprise_urls(cfg)
    if not urls:
        return False

    apobj = apprise.Apprise()
    for u in urls:
        try:
            apobj.add(u)
        except Exception as e:
            logger.warning(f"[NOTIFY] Could not add Apprise URL '{u}': {e}")

    if not len(apobj):
        return False

    notify_type = apprise.NotifyType.INFO
    if level in ("warning", "warn"):
        notify_type = apprise.NotifyType.WARNING
    elif level in ("critical", "alert", "error"):
        notify_type = apprise.NotifyType.FAILURE

    try:
        result = apobj.notify(
            body=message,
            title=title,
            notify_type=notify_type,
        )
        return bool(result)
    except Exception as e:
        logger.warning(f"[NOTIFY] Apprise push failed: {e}")
        return False


def send_notification(
    title: str | dict[str, Any],
    message: str = "",
    level: str = "normal",
    event_type: str = "general",
    dedup_key: str = "",
) -> dict[str, bool]:
    """
    Dispatch a notification to all configured channels with rate limiting and deduplication.
    Supports either positional args (title, message, level) or a single dictionary payload.
    """
    if isinstance(title, dict):
        d = title
        title = str(d.get("title", "ZettNAS Notification"))
        message = str(d.get("message", ""))
        level = str(d.get("level", "normal"))
        event_type = str(d.get("event_type", d.get("type", "general")))
        dedup_key = str(d.get("dedup_key", ""))

    cfg = load_notification_config()
    if not cfg.get("enabled", False):
        return {"dispatched": False, "reason": "disabled"}

    # Subsystem-specific event toggles
    type_toggle_map = {
        "smart": "notify_on_smart",
        "temp": "notify_on_temp",
        "fan": "notify_on_fan",
        "copy": "notify_on_copy",
        "ups": "notify_on_ups",
        "container": "notify_on_container",
        "backup": "notify_on_backup",
    }
    toggle_key = type_toggle_map.get(event_type)
    if toggle_key and not cfg.get(toggle_key, True):
        return {"dispatched": False, "reason": f"{event_type}_disabled"}

    now = time.time()
    cooldown = cfg.get("cooldown_seconds", 1800)

    # Deduplication logic
    if dedup_key:
        prev = _alert_history.get(dedup_key)
        if prev:
            elapsed = now - prev.get("last_sent", 0)
            prev_level = prev.get("last_level", "normal")
            is_escalation = prev_level in ("normal", "info", "warning", "warn") and level in (
                "critical",
                "alert",
                "error",
            )
            if elapsed < cooldown and not is_escalation:
                return {"dispatched": False, "reason": "cooldown"}

        _alert_history[dedup_key] = {"last_sent": now, "last_level": level}

    results: dict[str, bool] = {}

    # 1. Unraid native notification
    if cfg.get("unraid_notify", True):
        unraid_script = _find_unraid_notify()
        if unraid_script:
            results["unraid"] = _dispatch_unraid(unraid_script, title, message, level)

    # 2. Native ntfy & Webhook dispatch if configured
    if cfg.get("ntfy_enabled", False):
        results["ntfy"] = _dispatch_ntfy(cfg, title, message, level)
    if cfg.get("webhook_enabled", False):
        results["webhook"] = _dispatch_webhook(cfg, title, message, level)

    # 3. Apprise multi-channel dispatch (Discord, Telegram, SMTP, Apprise URLs)
    has_apprise_channels = any(
        [
            cfg.get("discord_enabled"),
            cfg.get("telegram_enabled"),
            cfg.get("email_enabled"),
            bool(cfg.get("apprise_urls")),
        ]
    )
    if has_apprise_channels:
        results["apprise"] = _dispatch_apprise(cfg, title, message, level)

    return {"dispatched": any(results.values()), "channels": results}


def test_notification(custom_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send an immediate test alert across all configured channels."""
    cfg = custom_cfg if custom_cfg is not None else load_notification_config()
    existing = load_notification_config()
    cfg = unmask_notification_config(cfg, existing)
    results = {}

    title = "ZettNAS Test Notification"
    message = "This is a test alert from your ZettNAS Toolkit. All notification routes are functioning normally!"
    level = "normal"

    if cfg.get("unraid_notify", True):
        script = _find_unraid_notify()
        results["unraid"] = _dispatch_unraid(script, title, message, level) if script else False

    if cfg.get("ntfy_enabled", False):
        results["ntfy"] = _dispatch_ntfy(cfg, title, message, level)
    if cfg.get("webhook_enabled", False):
        results["webhook"] = _dispatch_webhook(cfg, title, message, level)

    # Apprise dispatch for Discord, Telegram, Email, and raw URLs
    has_apprise_channels = any(
        [
            cfg.get("discord_enabled"),
            cfg.get("telegram_enabled"),
            cfg.get("email_enabled"),
            bool(cfg.get("apprise_urls")),
        ]
    )
    if has_apprise_channels:
        results["apprise"] = _dispatch_apprise(cfg, title, message, level)

    return {"status": "ok", "tested_channels": results}


def test_single_channel(channel: str, channel_cfg: dict[str, Any]) -> dict[str, Any]:
    """Test an individual notification channel and return status and latency in ms."""
    existing = load_notification_config()
    full_cfg = unmask_notification_config(channel_cfg, existing)

    t0 = time.perf_counter()
    title = f"ZettNAS Test: {channel.upper()}"
    message = f"Connection to {channel.capitalize()} tested successfully from ZettNAS Toolkit!"
    level = "info"

    success = False
    error_msg = ""

    try:
        if channel == "unraid":
            script = _find_unraid_notify()
            if script:
                success = _dispatch_unraid(script, title, message, level)
            else:
                error_msg = "Unraid notify binary not found (non-Unraid host)."
        elif channel == "discord":
            test_apprise_cfg = {
                "discord_enabled": True,
                "discord_webhook_url": full_cfg.get("discord_webhook_url", ""),
            }
            success = _dispatch_apprise(test_apprise_cfg, title, message, level)
            if not success:
                error_msg = "Discord dispatch failed. Verify webhook URL."
        elif channel == "telegram":
            test_apprise_cfg = {
                "telegram_enabled": True,
                "telegram_bot_token": full_cfg.get("telegram_bot_token", ""),
                "telegram_chat_id": full_cfg.get("telegram_chat_id", ""),
            }
            success = _dispatch_apprise(test_apprise_cfg, title, message, level)
            if not success:
                error_msg = "Telegram dispatch failed. Check bot token and chat ID."
        elif channel in ("email", "smtp"):
            test_apprise_cfg = {
                "email_enabled": True,
                "smtp_host": full_cfg.get("smtp_host", ""),
                "smtp_port": full_cfg.get("smtp_port", 587),
                "smtp_user": full_cfg.get("smtp_user", ""),
                "smtp_pass": full_cfg.get("smtp_pass", ""),
                "smtp_tls": full_cfg.get("smtp_tls", True),
                "email_from": full_cfg.get("email_from", ""),
                "email_to": full_cfg.get("email_to", ""),
            }
            success = _dispatch_apprise(test_apprise_cfg, title, message, level)
            if not success:
                error_msg = "SMTP delivery failed. Verify host, port, credentials, and TLS."
        elif channel == "ntfy":
            success = _dispatch_ntfy(full_cfg, title, message, level)
            if not success:
                error_msg = "ntfy push failed. Verify topic and server URL."
        elif channel == "webhook":
            success = _dispatch_webhook(full_cfg, title, message, level)
            if not success:
                error_msg = "Webhook delivery failed. Verify target URL."
        elif channel in ("apprise", "apprise_raw"):
            raw_urls = full_cfg.get("apprise_urls", [])
            test_apprise_cfg = {"apprise_urls": raw_urls}
            success = _dispatch_apprise(test_apprise_cfg, title, message, level)
            if not success:
                error_msg = "Apprise notification failed. Check URL syntax."
        else:
            error_msg = f"Unknown notification channel '{channel}'."
    except Exception as e:
        success = False
        error_msg = str(e)

    t1 = time.perf_counter()
    latency_ms = round((t1 - t0) * 1000)

    return {
        "status": "ok" if success else "error",
        "success": success,
        "latency_ms": latency_ms,
        "message": f"Delivered to {channel} in {latency_ms}ms" if success else error_msg,
    }
