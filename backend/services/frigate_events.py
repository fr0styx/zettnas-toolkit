"""Frigate's detections as ZettNAS notifications (COMP-11).

Frigate (App Catalog) records the cameras and finds people, cars and pets with the Intel iGPU
(OpenVINO). Once a minute ZettNAS asks its events API what it found since the last look and
sends the chosen ones as "camera" alerts, so they reach the same phone, e-mail and push
channels as every other alert, and people can route them to themselves under My alerts.

The catalog puts Frigate on ZettNAS's own Docker network, so the API is reached by name
(http://frigate:5000) and its unauthenticated port is never published. A camera and object
seen again within the cooldown is one alert, not a burst.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json

SETTINGS_FILE = f"{DATA_DIR}/frigate_events.json"
DEFAULT_URL = "http://frigate:5000"
LABELS = ("person", "car", "dog", "cat", "bicycle", "motorcycle", "bird")
_URL = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?/?$")
_CAMERA = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
FETCH_LIMIT = 50
SEEN_MAX = 500


def _defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "url": DEFAULT_URL,
        "labels": ["person"],
        "cameras": [],  # empty: every camera
        "min_score": 0.7,
        "cooldown_min": 5,
        "last_check": 0.0,
        "last_error": "",
        "seen": [],
        "last_sent": {},
    }


def settings() -> dict[str, Any]:
    return {**_defaults(), **(read_json(SETTINGS_FILE, {}) or {})}


def public() -> dict[str, Any]:
    s = settings()
    return {
        k: s[k]
        for k in ("enabled", "url", "labels", "cameras", "min_score", "cooldown_min", "last_check", "last_error")
    }


@json_locked(lambda *a, **k: SETTINGS_FILE)
def save_settings(
    enabled: bool | None = None,
    url: str | None = None,
    labels: list[str] | None = None,
    cameras: list[str] | None = None,
    min_score: float | None = None,
    cooldown_min: int | None = None,
) -> dict[str, Any]:
    s = settings()
    if url is not None:
        url = url.strip().rstrip("/") or DEFAULT_URL
        if not _URL.match(url + "/"):
            raise ValueError("Use Frigate's address, like http://frigate:5000.")
        s["url"] = url
    if labels is not None:
        bad = [x for x in labels if x not in LABELS]
        if bad or not labels:
            raise ValueError(f"Pick at least one of: {', '.join(LABELS)}.")
        s["labels"] = sorted(set(labels))
    if cameras is not None:
        if any(not _CAMERA.match(c) for c in cameras):
            raise ValueError("Camera names are the ones in Frigate's config: letters, digits, - and _.")
        s["cameras"] = sorted(set(cameras))
    if min_score is not None:
        s["min_score"] = max(0.3, min(float(min_score), 0.99))
    if cooldown_min is not None:
        s["cooldown_min"] = max(1, min(int(cooldown_min), 240))
    if enabled is not None:
        if enabled and not s.get("enabled"):
            s["last_check"] = time.time()  # start from now: no flood of old events
        s["enabled"] = bool(enabled)
    atomic_write_json(SETTINGS_FILE, s)
    return public()


def _get_json(url: str, timeout: float = 8) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - the admin's Frigate address
        body = r.read(2_000_000)
    try:
        return json.loads(body or b"null")
    except ValueError:
        return body.decode("utf-8", "replace").strip()  # /api/version answers in plain text


def fetch_events(base: str, after: float, labels: list[str], cameras: list[str], get: Callable = _get_json) -> list:
    q = {"after": str(int(after)), "limit": str(FETCH_LIMIT), "labels": ",".join(labels), "include_thumbnails": "0"}
    if cameras:
        q["cameras"] = ",".join(cameras)
    data = get(f"{base}/api/events?{urllib.parse.urlencode(q)}")
    return data if isinstance(data, list) else []


def _score(ev: dict[str, Any]) -> float:
    raw = ev.get("data")
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    for v in (data.get("top_score"), ev.get("top_score"), data.get("score"), ev.get("score")):
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def alert_for(ev: dict[str, Any]) -> dict[str, Any]:
    camera = str(ev.get("camera") or "camera")
    label = str(ev.get("label") or "object")
    zones = [str(z) for z in (ev.get("zones") or []) if z]
    where = f" in {', '.join(zones)}" if zones else ""
    when = time.strftime("%H:%M", time.localtime(float(ev.get("start_time") or time.time())))
    return {
        "type": "camera",
        "title": f"{label.capitalize()} on {camera}",
        "message": f"Frigate saw a {label} on {camera}{where} at {when} ({round(_score(ev) * 100)}% sure).",
        "level": "info",
        "dedup_key": f"frigate:{camera}:{label}",
    }


def pick(events: list, s: dict[str, Any], now: float) -> tuple[list[dict[str, Any]], dict[str, float], list[str]]:
    """The events to send: new ones, sure enough, outside their camera and object's cooldown."""
    seen = list(s.get("seen") or [])
    last_sent = dict(s.get("last_sent") or {})
    cooldown = float(s.get("cooldown_min") or 5) * 60
    out = []
    for ev in sorted((e for e in events if isinstance(e, dict)), key=lambda e: float(e.get("start_time") or 0)):
        eid = str(ev.get("id") or "")
        if not eid or eid in seen:
            continue
        seen.append(eid)
        if ev.get("false_positive") or _score(ev) < float(s.get("min_score") or 0):
            continue
        key = f"{ev.get('camera')}:{ev.get('label')}"
        if now - float(last_sent.get(key) or 0) < cooldown:
            continue
        last_sent[key] = now
        out.append(alert_for(ev))
    return out, last_sent, seen[-SEEN_MAX:]


@json_locked(lambda *a, **k: SETTINGS_FILE)
def _record(**fields: Any) -> None:
    s = settings()
    s.update(fields)
    atomic_write_json(SETTINGS_FILE, s)


def tick(now: float | None = None, get: Callable = _get_json, send: Callable | None = None) -> int:
    """One look at Frigate (called once a minute). Returns how many alerts were sent."""
    s = settings()
    if not s.get("enabled"):
        return 0
    now = now or time.time()
    after = float(s.get("last_check") or now) - 120  # events are listed when they start; overlap a little
    try:
        events = fetch_events(s["url"], after, s["labels"], s["cameras"], get)
    except (OSError, ValueError, urllib.error.URLError) as e:
        msg = f"Frigate didn't answer at {s['url']}: {getattr(e, 'reason', e)}"
        if msg != s.get("last_error"):
            logger.warning("[Frigate] %s", msg)
        _record(last_error=msg[:300])
        return 0
    alerts, last_sent, seen = pick(events, s, now)
    if send is None:
        from backend.services.notifications import send_notification as send
    for a in alerts:
        send(a)
    _record(last_check=now, last_error="", last_sent=last_sent, seen=seen)
    return len(alerts)


def check_connection(get: Callable = _get_json) -> dict[str, Any]:
    """Whether Frigate answers, its version and its cameras."""
    s = settings()
    try:
        cfg = get(f"{s['url']}/api/config")
        version = get(f"{s['url']}/api/version")
    except (OSError, ValueError, urllib.error.URLError) as e:
        return {"ok": False, "error": f"Frigate didn't answer at {s['url']}: {getattr(e, 'reason', e)}"}
    cams = sorted((cfg or {}).get("cameras") or {}) if isinstance(cfg, dict) else []
    return {"ok": True, "version": str(version or ""), "cameras": cams}
