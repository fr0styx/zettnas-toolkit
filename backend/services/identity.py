"""The server's name and time zone, chosen in the setup wizard (UX-17).

The name is shown in the browser tab and the interface. The time zone is applied to this
process (TZ + tzset), so schedules ("every day at 03:00") and log times follow it; without
one the container's own TZ stays in force."""

import os
import re
import time
from functools import lru_cache
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, locked_json, read_json

IDENTITY_FILE = os.path.join(DATA_DIR, "identity.json")
NAME_RE = re.compile(r"^[^\x00-\x1f<>]{1,40}$")


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    try:
        from zoneinfo import available_timezones

        return frozenset(available_timezones())
    except Exception:  # noqa: BLE001 - no tz database: only UTC can be checked
        return frozenset({"UTC"})


def get_identity() -> dict[str, Any]:
    data = read_json(IDENTITY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    zone = data.get("timezone") or ""
    source = (data.get("timezone_source") or "chosen") if zone else ("container" if os.environ.get("TZ") else "")
    return {
        "server_name": data.get("server_name") or "",
        "timezone": zone or os.environ.get("TZ", "") or "",
        # chosen (setup or Settings), browser (an administrator's, taken while none was set),
        # container (TZ from the container) or "" (nothing: night is night in UTC)
        "timezone_source": source,
    }


def known_timezone(tz: str) -> bool:
    return bool(tz) and tz in _zones()


def detect_timezone(tz: str) -> dict[str, Any]:
    """A server with no time zone takes the one an administrator's browser reports, so night
    work runs at their night. A zone already chosen, or TZ from the container, stays."""
    tz = (tz or "").strip()
    if not known_timezone(tz):
        raise ValueError(f"Unknown time zone: {tz}")
    with locked_json(IDENTITY_FILE):
        data = read_json(IDENTITY_FILE, {})
        data = data if isinstance(data, dict) else {}
        if data.get("timezone") or os.environ.get("TZ"):
            return get_identity()
        data["timezone"], data["timezone_source"] = tz, "browser"
        atomic_write_json(IDENTITY_FILE, data)
    apply_timezone(tz)
    logger.info("[Identity] time zone %s taken from an administrator's browser", tz)
    return get_identity()


def apply_timezone(tz: str) -> bool:
    if not tz or tz not in _zones():
        return False
    os.environ["TZ"] = tz
    if hasattr(time, "tzset"):
        time.tzset()
    return True


def set_identity(server_name: str | None = None, timezone: str | None = None) -> dict[str, Any]:
    """Saves what was given (None leaves a value as it is) and applies the time zone."""
    if server_name is not None:
        server_name = server_name.strip()
        if server_name and not NAME_RE.match(server_name):
            raise ValueError("Use up to 40 characters for the name, without < or >.")
    if timezone is not None:
        timezone = timezone.strip()
        if timezone and timezone not in _zones():
            raise ValueError(f"Unknown time zone: {timezone}")
    with locked_json(IDENTITY_FILE):
        data = read_json(IDENTITY_FILE, {})
        data = data if isinstance(data, dict) else {}
        if server_name is not None:
            data["server_name"] = server_name
        if timezone is not None:
            data["timezone"] = timezone
            data["timezone_source"] = "chosen" if timezone else ""
        atomic_write_json(IDENTITY_FILE, data)
    if timezone:
        apply_timezone(timezone)
    logger.info("[Identity] server name and time zone saved")
    return get_identity()


def apply_saved_timezone() -> None:
    """At startup: the time zone chosen in setup wins over the container's TZ."""
    tz = (read_json(IDENTITY_FILE, {}) or {}).get("timezone") if os.path.exists(IDENTITY_FILE) else None
    if tz and not apply_timezone(tz):
        logger.warning(f"[Identity] saved time zone {tz!r} is unknown here; keeping {os.environ.get('TZ', 'UTC')}")
