"""Anonymous health report, off unless the owner turns it on (docs/HEALTH_SIGNAL.md).

Once a week, when enabled, ZettNAS sends one small JSON object to the project's receiver:
the app version, storage platform, CPU architecture, image variant, a range for the number
of drives and which features are in use, under a random install id. Nothing else: no
hostname, IP address, user or share names, paths or hardware serials. Turning it off
forgets the id, so a later opt-in cannot be linked to the earlier one.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import secrets
import time
import urllib.request
from typing import Any

from backend import __version__

logger = logging.getLogger("ZettNAS")

# The project's receiver (tools/health-signal-worker). Empty until it is deployed; an install
# can point elsewhere with HEALTH_SIGNAL_URL. With no address the switch stays unavailable.
DEFAULT_ENDPOINT = ""
SCHEMA = 1
SEND_EVERY_SECS = 7 * 86400
CHECK_EVERY_SECS = 3600.0
RETRY_AFTER_FAILURE_SECS = 6 * 3600.0
TIMEOUT_SECS = 10
DRIVE_BUCKETS = ((0, "0"), (2, "1-2"), (4, "3-4"), (8, "5-8"), (16, "9-16"))

_next_check = 0.0  # monotonic; the poller asks every 10 s, the file is read at most hourly


def endpoint() -> str:
    return os.environ.get("HEALTH_SIGNAL_URL", "").strip() or DEFAULT_ENDPOINT


def _state_path() -> str:
    from backend import config

    return os.path.join(config.DATA_DIR, "health_signal.json")


def load_state() -> dict[str, Any]:
    state = {"enabled": False, "install_id": "", "last_sent": 0.0}
    try:
        with open(_state_path(), encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict):
            state.update({k: saved[k] for k in state if k in saved})
    except (OSError, ValueError):
        pass
    return state


def _save(state: dict[str, Any]) -> None:
    from backend.fsutil import atomic_write_json

    atomic_write_json(_state_path(), state)


def set_enabled(on: bool) -> dict[str, Any]:
    state = load_state()
    if on and not state["install_id"]:
        state["install_id"] = secrets.token_hex(16)
    if not on:
        state.update(install_id="", last_sent=0.0)  # forgotten: a new opt-in gets a new id
    state["enabled"] = bool(on)
    _save(state)
    return state


def drive_bucket(n: int) -> str:
    for top, label in DRIVE_BUCKETS:
        if n <= top:
            return label
    return "17+"


def _features() -> list[str]:
    """Which features are in use, from what is already in memory (no disk or network)."""
    from backend.state import Z_STATE

    found = set()
    stats = getattr(Z_STATE, "cached_stats", None) or {}
    hw = stats.get("hardware") or {}
    if hw.get("has_lcd"):
        found.add("lcd")
    if hw.get("has_mcu"):
        found.add("leds")
    if any((c or {}).get("state") == "running" for c in stats.get("docker") or []):
        found.add("containers")
    ups = stats.get("ups") or {}
    if ups.get("available") or ups.get("connected"):
        found.add("ups")
    return sorted(found)


def _platform() -> str:
    try:
        from backend.hardware.pal_storage import StoragePlatformDetector

        name = StoragePlatformDetector.detect().value
    except Exception:
        name = ""
    return "".join(c for c in str(name).lower() if c.isalnum() or c == "_")[:24] or "unknown"


def report(install_id: str) -> dict[str, Any]:
    """Exactly what is sent (the settings card shows it before you turn this on)."""
    from backend import config
    from backend.state import Z_STATE

    disks = (getattr(Z_STATE, "cached_stats", None) or {}).get("disks") or []
    return {
        "schema": SCHEMA,
        "id": install_id,
        "version": __version__,
        "platform": _platform(),
        "arch": platform.machine() or "unknown",
        "variant": getattr(config, "IMAGE_VARIANT", "full"),
        "drives": drive_bucket(len(disks)),
        "features": _features(),
    }


def send(state: dict[str, Any]) -> bool:
    body = json.dumps(report(state["install_id"])).encode("utf-8")
    req = urllib.request.Request(
        endpoint(),
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": f"ZettNAS/{__version__}"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECS) as resp:
        return 200 <= resp.status < 300


def maybe_send(now: float | None = None, mono: float | None = None) -> bool:
    """Called from the SMART poller every 10 s; sends at most once a week, only when enabled."""
    global _next_check
    mono = time.monotonic() if mono is None else mono
    if mono < _next_check:
        return False
    _next_check = mono + CHECK_EVERY_SECS
    if not endpoint():
        return False
    state = load_state()
    now = time.time() if now is None else now
    if not state["enabled"] or not state["install_id"] or now - float(state["last_sent"] or 0) < SEND_EVERY_SECS:
        return False
    try:
        ok = send(state)
    except Exception as e:  # offline, receiver down: try again later, quietly
        logger.info(f"[Health signal] Weekly report not sent: {type(e).__name__}")
        ok = False
    if ok:
        state["last_sent"] = now
        _save(state)
    else:
        _next_check = mono + RETRY_AFTER_FAILURE_SECS
    return ok


def status() -> dict[str, Any]:
    state = load_state()
    preview = report(state["install_id"] or "(a random id, made when you turn this on)")
    return {
        "enabled": bool(state["enabled"]),
        "available": bool(endpoint()),
        "last_sent": float(state["last_sent"] or 0),
        "preview": preview,
    }
