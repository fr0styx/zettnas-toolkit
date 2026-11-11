"""What state an app is really in (SET-14).

The list of apps had two looks: green for "running" and grey for everything else. "Up 2 days
(unhealthy)" was green, and an app that had crashed or was caught in a restart loop was the same
quiet grey as one somebody had stopped. This module turns what Docker reports into one word a
page can show, and says whether somebody should look.

Kiboto records its own stops (stopped.json in the data folder): Docker reports exit code 137 for
an app that ignored the stop signal and was then ended, which is also what an app killed for
using too much memory reports. Without the record, "stopped by you" and "crashed" look the same.
"""

from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

from backend import config
from backend.fsutil import atomic_write_json

_EXITED = re.compile(r"^Exited \((\d+)\)")
_HEALTH = re.compile(r"\((healthy|unhealthy|health: starting)\)")
_STOP_SIGNALS = (137, 143)  # ended by SIGKILL or SIGTERM: a stop, unless Docker says it ran out of memory
NEEDS_LOOK = ("unhealthy", "restarting", "crashed", "dead")
_LOCK = threading.Lock()
_stopped: set[str] | None = None


def _file() -> str:
    return os.path.join(config.DATA_DIR, "docker_stopped.json")


def _load() -> set[str]:
    global _stopped
    if _stopped is None:
        try:
            with open(_file(), encoding="utf-8") as f:
                data = json.load(f)
            _stopped = {str(x) for x in data} if isinstance(data, list) else set()
        except (OSError, ValueError):
            _stopped = set()
    return _stopped


def note_stopped(*keys: str) -> None:
    """Kiboto stopped this app (by id or name): it is "stopped", whatever exit code follows."""
    with _LOCK:
        known = _load()
        before = len(known)
        known.update(k for k in keys if k)
        if len(known) != before:
            _save(known)


def note_started(*keys: str) -> None:
    with _LOCK:
        known = _load()
        gone = known & {k for k in keys if k}
        if gone:
            known -= gone
            _save(known)


def _save(known: set[str]) -> None:
    try:
        atomic_write_json(_file(), sorted(known))
    except OSError:
        config.logger.warning("[Docker] The list of apps Kiboto stopped could not be saved", exc_info=True)


def stopped_by_kiboto(*keys: str) -> bool:
    with _LOCK:
        return bool(_load() & {k for k in keys if k})


def forget_missing(present: set[str]) -> None:
    """Drops the record of apps that no longer exist, so the file does not grow for ever."""
    with _LOCK:
        known = _load()
        gone = known - present
        if gone:
            known -= gone
            _save(known)


def exit_code(status: str) -> int | None:
    m = _EXITED.match(status or "")
    return int(m.group(1)) if m else None


def health(status: str) -> str:
    """ "healthy", "unhealthy" or "starting" for an app with a health check; "" for one without."""
    m = _HEALTH.search(status or "")
    return {"health: starting": "starting"}.get(m.group(1), m.group(1)) if m else ""


def describe(state: str, status: str, by_kiboto: bool = False, inspect: dict[str, Any] | None = None) -> dict[str, Any]:
    """{condition, needs_look, health, exit_code, restart_count, reason} for one app."""
    info = (inspect or {}).get("State") or {}
    code = exit_code(status)
    if code is None and isinstance(info.get("ExitCode"), int) and state in ("exited", "dead"):
        code = info["ExitCode"]
    well = health(status)
    reason = ""
    if state == "running":
        condition = {"unhealthy": "unhealthy", "starting": "starting"}.get(well, "running")
    elif state == "exited":
        if info.get("OOMKilled"):
            condition, reason = "crashed", "out_of_memory"
        elif code == 0 or by_kiboto:
            condition = "stopped"
        elif code in _STOP_SIGNALS:
            condition, reason = "stopped", "stopped_outside"  # something else on the host stopped it
        else:
            condition, reason = "crashed", "exit_code"
    elif state in ("restarting", "paused", "created", "dead", "removing"):
        condition = state
    else:
        condition = "unknown"
    restarts = (inspect or {}).get("RestartCount")
    return {
        "condition": condition,
        "needs_look": condition in NEEDS_LOOK,
        "health": well,
        "exit_code": code,
        "restart_count": restarts if isinstance(restarts, int) else 0,
        "reason": reason,
    }
