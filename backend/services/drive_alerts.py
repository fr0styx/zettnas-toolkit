"""Drive alerts a family can trust (REL-7).

A drive's condition is alerted only when its Drive Health verdict changes (Healthy, Keep an eye
on it, Replace soon, Replace now), once per change, with a daily reminder while it says "Replace
now". The verdict is remembered per drive by its WWN or serial, not its kernel name, so a disk
that comes back as sdc after a reboot is not mistaken for another one.

Temperature is alerted once when a drive crosses its threshold and again only after it has
cooled a few degrees below it, instead of every half hour while it sits at the threshold.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from backend import config
from backend.fsutil import atomic_write_json, locked_json, read_json

ORDER = {"ok": 0, "watch": 1, "soon": 2, "now": 3}
LEVEL = {"watch": "warning", "soon": "error", "now": "critical"}
REMIND_SECS = 24 * 3600
TEMP_REARM_C = 3
_lock = threading.Lock()
_hot: dict[str, str] = {}  # drive -> "warn" | "crit" while it is above its threshold


def _state_file() -> str:
    return os.path.join(config.DATA_DIR, "drive_alerts.json")


def _send(**kwargs: Any) -> None:
    from backend.services.notifications import send_notification

    threading.Thread(target=send_notification, kwargs=kwargs, daemon=True, name="DriveAlert").start()


def on_verdict(
    dev: str, result: dict, key: str | None = None, now: float | None = None, send: Callable[..., None] | None = None
) -> str:
    """Records a drive's verdict and alerts when it changed. `key` is the drive's lasting name
    (WWN or serial, from the hardware layer). Returns what was done:
    "alert", "reminder", "better", "first", or "" (nothing new)."""
    verdict = str(result.get("verdict") or "")
    if verdict not in ORDER:
        return ""
    now = now or time.time()
    send = send or _send
    key = key or f"dev:{dev}"
    with _lock, locked_json(_state_file()):
        state = read_json(_state_file(), {}) or {}
        prev = state.get(key) or {}
        before = prev.get("verdict")
        action = ""
        if not before:
            action = "alert" if ORDER[verdict] >= ORDER["soon"] else "first"
        elif before != verdict:
            action = "alert" if ORDER[verdict] > ORDER[before] else "better"
        elif verdict == "now" and now - float(prev.get("notified") or 0) >= REMIND_SECS:
            action = "reminder"
        if not action:
            return ""
        entry = {"verdict": verdict, "dev": dev, "since": now if before != verdict else prev.get("since", now)}
        entry["notified"] = now if action in ("alert", "reminder") else prev.get("notified", 0)
        state[key] = entry
        atomic_write_json(_state_file(), state)
    label = result.get("label") or verdict
    summary = result.get("summary") or ""
    if action in ("alert", "reminder"):
        from backend.state import add_event

        title = f"Drive {dev}: {label}"
        message = f"{summary}. Open Drive Health for what to do." if summary else "Open Drive Health for what to do."
        add_event("error" if verdict in ("soon", "now") else "warning", title, message)
        send(
            title=title,
            message=message,
            level=LEVEL.get(verdict, "warning"),
            event_type="smart",
            dedup_key=f"drive_verdict_{key}_{verdict}_{int(now // REMIND_SECS) if action == 'reminder' else 0}",
        )
    elif action == "better":
        from backend.state import add_event

        add_event("info", f"Drive {dev}: {label}", summary or "The drive looks better than before.")
    return action


def check_temperatures(
    drives: list[dict], hdd_warn: int, send: Callable[..., None], limits: dict[str, int] | None = None
) -> list[str]:
    """Alerts each drive once when it crosses its warning or critical temperature; re-arms after it
    has cooled TEMP_REARM_C below the warning level. Returns the drives alerted now. `limits` are
    the owners' own warning levels by dev (Drive Health details); critical is 10 °C above them."""
    from backend.config import NVME_CRITICAL_TEMP, NVME_WARN_TEMP

    alerted = []
    for d in drives or []:
        dev = d.get("dev") or d.get("name")
        temp = d.get("temp")
        if not dev or temp is None or d.get("standby"):
            continue
        nvme = bool(d.get("is_nvme"))
        own = (limits or {}).get(dev)
        warn = own or (NVME_WARN_TEMP if nvme else int(hdd_warn or 50))
        crit = own + 10 if own else (NVME_CRITICAL_TEMP if nvme else max(60, warn + 5))
        level = "crit" if temp >= crit else "warn" if temp >= warn else ""
        prev = _hot.get(dev, "")
        if level and (not prev or (level == "crit" and prev == "warn")):
            _hot[dev] = level
            alerted.append(dev)
            send(
                title=f"Drive {dev} is {'too hot' if level == 'crit' else 'running hot'} ({temp}°C)",
                message=f"Drive {dev} reached {temp}°C. Check that the fans run and the vents are free.",
                level="critical" if level == "crit" else "warning",
                event_type="temp",
                dedup_key=f"drive_temp_{dev}_{level}",
            )
        elif not level and prev and temp <= warn - TEMP_REARM_C:
            _hot.pop(dev, None)
    return alerted
