import json
import os
import subprocess
import time
import urllib.parse
from typing import Any

import apprise
import httpx

from backend.ignored_errors import ignored

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
            ignored("backend.services.notifications.close_notification_client")
        _http_client = None


from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json

NOTIFICATIONS_FILE = os.path.join(DATA_DIR, "notifications.json")

MASK_PLACEHOLDER = "********"
SECRET_FIELDS = {"smtp_pass", "telegram_bot_token", "ntfy_token", "discord_webhook_url", "webhook_url", "apprise_urls"}

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
    # Daily digest (Batch 6): critical alerts go out at once, everything else in one summary
    "digest_mode": "off",  # "off" or "daily"
    "digest_hour": 8,
    "weekly_report": True,  # a health summary on Sunday mornings (B12a, FEAT-05)
}

DIGEST_FILE = os.path.join(DATA_DIR, "notification_digest.json")
OUTBOX_FILE = os.path.join(DATA_DIR, "notification_outbox.json")
# an alert whose channels all failed is tried again after these waits, then given up (REL-22)
RETRY_DELAYS = (60, 300, 900, 3600, 3600, 3600)
OUTBOX_MAX = 200
ROUTES_FILE = os.path.join(DATA_DIR, "notification_routes.json")
URGENT_LEVELS = ("critical", "alert", "error")
ROUTABLE_EVENTS = (
    "smart",
    "storage",
    "temp",
    "fan",
    "ups",
    "copy",
    "container",
    "backup",
    "security",
    "health",
    "general",
)
_LEVEL_RANK = {"info": 0, "normal": 0, "warning": 1, "warn": 1, "critical": 2, "alert": 2, "error": 2}

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
        val = masked.get(field)
        if val:
            if isinstance(val, list):
                masked[field] = [MASK_PLACEHOLDER if v else "" for v in val]
            else:
                masked[field] = MASK_PLACEHOLDER
    return masked


def unmask_notification_config(new_cfg: dict[str, Any], existing_cfg: dict[str, Any]) -> dict[str, Any]:
    """Restore existing secret values if the caller sent back the MASK_PLACEHOLDER."""
    resolved = dict(new_cfg)
    for field in SECRET_FIELDS:
        val = resolved.get(field)
        if val == MASK_PLACEHOLDER:
            resolved[field] = existing_cfg.get(field, "")
        elif isinstance(val, list):
            exist_list = existing_cfg.get(field, [])
            resolved[field] = [
                exist_list[i] if (i < len(exist_list) and v == MASK_PLACEHOLDER) else v for i, v in enumerate(val)
            ]
    return resolved


@json_locked(lambda *a, **k: NOTIFICATIONS_FILE)
def save_notification_config(cfg: dict[str, Any]) -> None:
    existing = load_notification_config()
    # keys the caller did not send keep their saved value (a field the form doesn't know about
    # is not reset to its default)
    merged = {**existing, **unmask_notification_config(cfg, existing)}
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
) -> dict[str, Any]:
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
    # Phones with the app installed get alerts even if no other channel is set up (M1)
    push_on = False
    if cfg.get("push_enabled", True):
        try:
            from backend.services import web_push

            push_on = bool(web_push.subscriptions())
        except Exception:
            logger.debug("notifications: push unavailable", exc_info=True)
    shared_off = not cfg.get("enabled", False) and not push_on

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

    # Deduplication logic: the cooldown counts from the last alert that got through (REL-22)
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
        if _queued(dedup_key):
            return {"dispatched": False, "reason": "queued"}  # already waiting for a retry

    # Each person's own alerts (Batch 6), whether or not the shared channels are on (REL-6)
    _route_to_people(cfg, str(title), str(message), level, event_type)
    if shared_off:
        return {"dispatched": False, "reason": "disabled"}

    # Daily digest: only urgent alerts go out now
    if cfg.get("digest_mode") == "daily" and level not in URGENT_LEVELS:
        _queue_for_digest(str(title), str(message), level, event_type, now)
        return {"dispatched": False, "reason": "digest"}

    res = _dispatch_shared(cfg, str(title), str(message), level, push_on)
    if res["dispatched"]:
        if dedup_key:
            _alert_history[dedup_key] = {"last_sent": now, "last_level": level}
    elif res["channels"]:
        _enqueue(str(title), str(message), level, event_type, dedup_key, now)  # every channel failed
        res["reason"] = "queued for retry"
    return res


def _dispatch_shared(cfg: dict[str, Any], title: str, message: str, level: str, push_on: bool) -> dict[str, Any]:
    """Phones, Unraid, ntfy, webhooks and Apprise: {dispatched, channels}."""
    results: dict[str, bool] = {}

    if push_on:
        try:
            from backend.services import web_push

            sent = web_push.notify(str(title), str(message), level=level)
            results["push"] = any(200 <= s < 300 for s in sent.values())
        except Exception:
            logger.warning("[Notify] Push dispatch failed", exc_info=True)
            results["push"] = False
    if not cfg.get("enabled", False):
        return {"dispatched": any(results.values()), "channels": results}

    # 1. Unraid native notification: the local notify script, or the Unraid API when
    #    ZettNAS runs elsewhere (companion mode, D5)
    if cfg.get("unraid_notify", True):
        unraid_script = _find_unraid_notify()
        if unraid_script:
            results["unraid"] = _dispatch_unraid(unraid_script, title, message, level)
        else:
            from backend.services import unraid_api

            if unraid_api.configured():
                results["unraid"] = unraid_api.notify(title, message, level)

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


# ---------------------------------------------------------------------------
# The outbox: alerts whose channels all failed, tried again with growing waits (REL-22)
# ---------------------------------------------------------------------------
def _outbox() -> list[dict[str, Any]]:
    data = read_json(OUTBOX_FILE, {}) or {}
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _queued(dedup_key: str) -> bool:
    return bool(dedup_key) and any(i.get("dedup_key") == dedup_key for i in _outbox())


@json_locked(lambda *a, **k: OUTBOX_FILE)
def _enqueue(title: str, message: str, level: str, event_type: str, dedup_key: str, now: float) -> None:
    items = _outbox()
    items.append(
        {
            "title": title[:200],
            "message": message[:2000],
            "level": level,
            "event_type": event_type,
            "dedup_key": dedup_key,
            "attempts": 1,
            "first_at": now,
            "next_try": now + RETRY_DELAYS[0],
        }
    )
    atomic_write_json(OUTBOX_FILE, {"items": items[-OUTBOX_MAX:]})
    logger.warning(f"[Notify] '{title}' could not be sent on any channel; it is retried in a minute")


@json_locked(lambda *a, **k: OUTBOX_FILE)
def retry_outbox(now: float | None = None) -> dict[str, list[str]]:
    """From the scheduler every minute: sends the alerts that are due again."""
    now = now or time.time()
    items = _outbox()
    if not items:
        return {"sent": [], "retry": [], "dropped": []}
    cfg = load_notification_config()
    push_on = False
    if cfg.get("push_enabled", True):
        try:
            from backend.services import web_push

            push_on = bool(web_push.subscriptions())
        except Exception:
            push_on = False
    out: dict[str, list[str]] = {"sent": [], "retry": [], "dropped": []}
    keep = []
    for item in items:
        if float(item.get("next_try") or 0) > now:
            keep.append(item)
            continue
        res = _dispatch_shared(cfg, item["title"], item["message"], item.get("level", "normal"), push_on)
        if res["dispatched"]:
            if item.get("dedup_key"):
                _alert_history[item["dedup_key"]] = {"last_sent": now, "last_level": item.get("level")}
            out["sent"].append(item["title"])
            continue
        attempts = int(item.get("attempts") or 1)
        if attempts > len(RETRY_DELAYS) - 1:
            out["dropped"].append(item["title"])
            logger.error(f"[Notify] Gave up sending '{item['title']}' after {attempts + 1} tries")
            try:
                from backend.state import add_event

                add_event("error", "An alert could not be sent", f"{item['title']}: every channel failed for hours.")
            except Exception:
                logger.debug("notifications: could not record the dropped alert", exc_info=True)
            continue
        item["attempts"] = attempts + 1
        item["next_try"] = now + RETRY_DELAYS[attempts]
        keep.append(item)
        out["retry"].append(item["title"])
    atomic_write_json(OUTBOX_FILE, {"items": keep})
    return out


# ---------------------------------------------------------------------------
# Daily digest and per-person routing (Batch 6)
# ---------------------------------------------------------------------------
@json_locked(lambda *a, **k: DIGEST_FILE)
def _queue_for_digest(title: str, message: str, level: str, event_type: str, now: float) -> None:
    data = read_json(DIGEST_FILE, {}) or {}
    items = data.get("items") or []
    items.append({"ts": now, "title": title[:200], "message": message[:500], "level": level, "type": event_type})
    data["items"] = items[-500:]
    atomic_write_json(DIGEST_FILE, data)


def digest_text(items: list[dict[str, Any]]) -> tuple[str, str]:
    by_type: dict[str, int] = {}
    for it in items:
        by_type[it.get("type") or "general"] = by_type.get(it.get("type") or "general", 0) + 1
    summary = ", ".join(f"{n} {t}" for t, n in sorted(by_type.items(), key=lambda x: -x[1]))
    lines = [f"- {time.strftime('%H:%M', time.localtime(it['ts']))} {it['title']}" for it in items[-20:]]
    more = f"\n... and {len(items) - 20} more" if len(items) > 20 else ""
    return f"ZettNAS daily summary: {len(items)} alerts", f"{summary}\n\n" + "\n".join(lines) + more


@json_locked(lambda *a, **k: DIGEST_FILE)
def send_digest_if_due(now: float | None = None) -> dict[str, Any]:
    """Called by the scheduler every minute: sends the day's summary at the digest hour."""
    cfg = load_notification_config()
    now = now or time.time()
    if cfg.get("digest_mode") != "daily":
        return {"sent": False, "reason": "off"}
    data = read_json(DIGEST_FILE, {}) or {}
    t = time.localtime(now)
    if t.tm_hour != int(cfg.get("digest_hour", 8)) or now - float(data.get("last_sent") or 0) < 20 * 3600:
        return {"sent": False, "reason": "not due"}
    items = data.get("items") or []
    data["last_sent"] = now
    data["items"] = []
    atomic_write_json(DIGEST_FILE, data)
    if not items:
        return {"sent": False, "reason": "nothing to report"}
    title, body = digest_text(items)
    saved = dict(cfg)
    saved["digest_mode"] = "off"  # send this one through the channels directly
    res = _dispatch_configured(saved, title, body, "normal")
    return {"sent": True, "count": len(items), "channels": res}


def _dispatch_configured(cfg: dict[str, Any], title: str, message: str, level: str) -> dict[str, bool]:
    results: dict[str, bool] = {}
    if not cfg.get("enabled", False):
        return results
    if cfg.get("ntfy_enabled", False):
        results["ntfy"] = _dispatch_ntfy(cfg, title, message, level)
    if cfg.get("webhook_enabled", False):
        results["webhook"] = _dispatch_webhook(cfg, title, message, level)
    if any(
        [
            cfg.get("discord_enabled"),
            cfg.get("telegram_enabled"),
            cfg.get("email_enabled"),
            bool(cfg.get("apprise_urls")),
        ]
    ):
        results["apprise"] = _dispatch_apprise(cfg, title, message, level)
    return results


def get_routes() -> dict[str, dict[str, Any]]:
    return (read_json(ROUTES_FILE, {}) or {}).get("people") or {}


def get_route(username: str) -> dict[str, Any]:
    return get_routes().get(username) or {
        "ntfy_topic": "",
        "email": "",
        "events": ["ups", "security", "backup"],
        "min_level": "warning",
    }


@json_locked(lambda *a, **k: ROUTES_FILE)
def set_route(
    username: str, ntfy_topic: str = "", email: str = "", events: list[str] | None = None, min_level: str = "warning"
) -> dict[str, Any]:
    import re as _re

    topic = (ntfy_topic or "").strip()
    if topic and not _re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        raise ValueError("An ntfy topic uses letters, digits, - and _.")
    addr = (email or "").strip()
    if addr and (len(addr) > 254 or not _re.fullmatch(r"[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+", addr)):
        raise ValueError("That doesn't look like an e-mail address.")
    route = {
        "ntfy_topic": topic,
        "email": addr,
        "events": [e for e in (events or []) if e in ROUTABLE_EVENTS],
        "min_level": min_level if min_level in ("info", "warning", "critical") else "warning",
    }
    data = read_json(ROUTES_FILE, {}) or {}
    data.setdefault("people", {})[username] = route
    atomic_write_json(ROUTES_FILE, data)
    return route


ADMIN_ONLY_EVENTS = ("security",)


def may_receive(username: str, event_type: str) -> bool:
    """Security alerts (sign-in attacks, the ransomware guard) go to admins only (SEC-8)."""
    if event_type not in ADMIN_ONLY_EVENTS:
        return True
    try:
        from backend.auth import has_scope
        from backend.users_db import get_role, get_user_by_username

        user = get_user_by_username(username) or {}
        role = get_role(str(user.get("role_id") or "")) or {}
        scopes = json.loads(role.get("scopes_json") or "[]")
        return user.get("status") == "active" and (has_scope(scopes, "*") or has_scope(scopes, "audit:read"))
    except Exception:
        logger.debug("notifications: could not check who may get security alerts", exc_info=True)
        return False


def notify_person(username: str, title: str, message: str, level: str = "warning") -> bool:
    """Tells one person about something done to their account (B11, SEC-30): on their own alert
    route if they set one, else to their account email when mail is set up. False when neither."""
    if not username:
        return False
    cfg = load_notification_config()
    route = get_routes().get(username) or {}
    email = route.get("email") or ""
    if not email:
        try:
            from backend.users_db import get_user_by_username

            email = (get_user_by_username(username) or {}).get("email") or ""
        except Exception:
            email = ""
    sent = False
    try:
        if route.get("ntfy_topic"):
            sent = bool(_dispatch_ntfy({**cfg, "ntfy_topic": route["ntfy_topic"]}, title, message, level)) or sent
        if email and cfg.get("smtp_host"):
            only_mail = {
                **cfg,
                "email_enabled": True,
                "email_to": email,
                "discord_enabled": False,
                "telegram_enabled": False,
                "apprise_urls": [],
            }
            sent = bool(_dispatch_apprise(only_mail, title, message, level)) or sent
    except Exception:
        logger.warning(f"[Notify] message for {username} failed", exc_info=True)
    return sent


def _route_to_people(cfg: dict[str, Any], title: str, message: str, level: str, event_type: str) -> list[str]:
    """Sends an alert to everyone who asked for this kind, at this level or above."""
    sent = []
    rank = _LEVEL_RANK.get(level, 0)
    for username, r in get_routes().items():
        if event_type not in r.get("events", []) or rank < _LEVEL_RANK.get(r.get("min_level", "warning"), 1):
            continue
        if not may_receive(username, event_type):
            continue
        try:
            if r.get("ntfy_topic"):
                _dispatch_ntfy({**cfg, "ntfy_topic": r["ntfy_topic"]}, title, message, level)
            if r.get("email") and cfg.get("smtp_host"):
                _dispatch_apprise(
                    {
                        **cfg,
                        "email_enabled": True,
                        "email_to": r["email"],
                        "discord_enabled": False,
                        "telegram_enabled": False,
                        "apprise_urls": [],
                    },
                    title,
                    message,
                    level,
                )
            sent.append(username)
        except Exception:
            logger.warning(f"[Notify] personal alert for {username} failed", exc_info=True)
    return sent
