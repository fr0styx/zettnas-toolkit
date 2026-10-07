import json
import os
import subprocess
import time
import urllib.request
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

DEFAULT_NOTIFICATION_CONFIG = {
    "enabled": False,
    # Channels
    "unraid_notify": True,
    "apprise_urls": [],  # List of apprise URLs (e.g. 'discord://...', 'slack://...', 'tgram://...')
    # Legacy fields (kept for compatibility with old UI temporarily if needed)
    "ntfy_enabled": False,
    "ntfy_url": "https://ntfy.sh",
    "ntfy_topic": "",
    "ntfy_token": "",
    "webhook_enabled": False,
    "webhook_url": "",
    # Event triggers
    "notify_on_smart": True,
    "notify_on_temp": True,
    "notify_on_fan": True,
    "notify_on_copy": True,
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


def save_notification_config(cfg: dict[str, Any]) -> None:
    merged = load_notification_config()
    merged.update(cfg)
    atomic_write_json(NOTIFICATIONS_FILE, merged)


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
        "warning": "4",
        "warn": "4",
        "critical": "5",
        "alert": "5",
        "error": "5",
    }
    priority = priority_map.get(level, "3")

    tags_map = {
        "normal": "information_source",
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
    # Build Apprise instance
    apobj = apprise.Apprise()

    # 1. Add explicitly configured Apprise URLs
    urls = cfg.get("apprise_urls", [])
    if isinstance(urls, str):
        urls = [urls]

    for url in urls:
        if url.strip():
            apobj.add(url.strip())

    # 2. Translate legacy configuration into Apprise URLs
    if cfg.get("ntfy_enabled") and cfg.get("ntfy_topic"):
        topic = cfg.get("ntfy_topic", "").strip()
        base_url = (
            cfg.get("ntfy_url", "https://ntfy.sh")
            .rstrip("/")
            .replace("https://", "ntfys://")
            .replace("http://", "ntfy://")
        )
        url = f"{base_url}/{topic}"
        token = cfg.get("ntfy_token", "").strip()
        if token:
            url += f"?token={token}"
        apobj.add(url)

    if cfg.get("webhook_enabled") and cfg.get("webhook_url"):
        wb_url = cfg.get("webhook_url", "").strip()
        # Very basic apprise webhook mapping or rely on apprise parsing discord directly
        if "discord.com" in wb_url or "discordapp.com" in wb_url:
            # apprise handles discord webhooks automatically if prefixed with discord://
            # but natively discord webhooks are http URLs, let's just pass it to apprise
            pass
        apobj.add(wb_url)

    if not len(apobj):
        return False

    # Map our level to Apprise NotifyType
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
        return result
    except Exception as e:
        logger.warning(f"[NOTIFY] Apprise push failed: {e}")
        return False


def send_notification(
    title: str,
    message: str,
    level: str = "normal",
    event_type: str = "general",
    dedup_key: str = "",
) -> dict[str, bool]:
    """
    Dispatch a notification to all configured channels with rate limiting and deduplication.
    """
    cfg = load_notification_config()
    if not cfg.get("enabled", False):
        return {"dispatched": False, "reason": "disabled"}

    # Event-specific toggles
    type_toggle_map = {
        "smart": "notify_on_smart",
        "temp": "notify_on_temp",
        "fan": "notify_on_fan",
        "copy": "notify_on_copy",
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
            # Only suppress if within cooldown AND level hasn't escalated
            is_escalation = prev_level in ("normal", "warning", "warn") and level in ("critical", "alert", "error")
            if elapsed < cooldown and not is_escalation:
                return {"dispatched": False, "reason": "cooldown"}

        _alert_history[dedup_key] = {"last_sent": now, "last_level": level}

    results = {}

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

    # 3. Apprise notifications (for explicitly configured Apprise URLs or multi-channel)
    if cfg.get("apprise_urls"):
        results["apprise"] = _dispatch_apprise(cfg, title, message, level)

    return {"dispatched": any(results.values()), "channels": results}


def test_notification(custom_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send an immediate test alert to verify notification channels."""
    cfg = custom_cfg if custom_cfg is not None else load_notification_config()
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
    if cfg.get("apprise_urls"):
        results["apprise"] = _dispatch_apprise(cfg, title, message, level)

    return {"status": "ok", "tested_channels": results}
