"""What the owner knows about a drive and S.M.A.R.T. doesn't: when it was bought, until when its
warranty runs, a note (where it sits, the shop, the order number), and the temperature above
which it counts as warm (an NVMe drive or a hot room may need another one than the usual).

Kept by serial number in the data folder, so the details follow the drive to another bay or
device name. Drive Health shows them, puts them in its reports, and points out a failing drive
that is still under warranty. The temperature limit sets its "runs warm" finding and its
temperature alert ("too hot" is 10 °C above it).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

NOTES_FILE = os.path.join(DATA_DIR, "drive_notes.json")
SERIAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+-]{0,63}$")
NOTE_MAX = 300
MAX_DRIVES = 500
TEMP_MIN, TEMP_MAX = 30, 90
_lock = threading.Lock()
_cache: dict[str, Any] = {"key": None, "data": {}}  # the file as last read, by (path, mtime)


class BadNotes(ValueError):
    """Details that can't be stored; the message says why."""


def _load() -> dict[str, dict[str, Any]]:
    try:
        key = (NOTES_FILE, os.stat(NOTES_FILE).st_mtime_ns)
    except FileNotFoundError:
        return {}
    except OSError:
        key = None
    if key is not None and _cache["key"] == key:
        return {k: dict(v) for k, v in _cache["data"].items()}
    try:
        with open(NOTES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("drive_notes: %s could not be read; starting empty", NOTES_FILE, exc_info=True)
        return {}
    out = {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    _cache.update(key=key, data=out)
    return {k: dict(v) for k, v in out.items()}


def all_notes() -> dict[str, dict[str, Any]]:
    with _lock:
        return _load()


def temp_limit_for(*serials: Any) -> int | None:
    """The owner's temperature limit for a drive known by any of these serial spellings."""
    wanted = {str(s or "").strip().upper() for s in serials} - {""}
    if not wanted:
        return None
    for serial, entry in all_notes().items():
        if serial.strip().upper() in wanted and isinstance(entry.get("temp_limit"), int):
            return entry["temp_limit"]
    return None


def temp_limits_for_devs(serial_by_dev: dict[str, str]) -> dict[str, int]:
    """dev -> the owner's temperature limit, for the drives that have one."""
    by_serial = {k.strip().upper(): v.get("temp_limit") for k, v in all_notes().items()}
    out = {}
    for dev, serial in (serial_by_dev or {}).items():
        limit = by_serial.get(str(serial or "").strip().upper())
        if isinstance(limit, int):
            out[dev] = limit
    return out


def _limit(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise BadNotes("The temperature limit must be a whole number of °C.") from None
    if not TEMP_MIN <= n <= TEMP_MAX:
        raise BadNotes(f"The temperature limit must be between {TEMP_MIN} and {TEMP_MAX} °C.")
    return n


def _date(value: Any, what: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        day = dt.date.fromisoformat(text)
    except ValueError:
        raise BadNotes(f"{what} must be a date like 2026-05-31.") from None
    if not 1990 <= day.year <= 2100:
        raise BadNotes(f"{what} must be a date between 1990 and 2100.")
    return day.isoformat()


def clean_note(value: Any) -> str:
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or ""))
    return text.strip()[:NOTE_MAX]


def save(
    serial: str, bought: Any = "", warranty_until: Any = "", note: Any = "", temp_limit: Any = None
) -> dict[str, Any] | None:
    """Stores the details for `serial` and returns them; all empty removes them (returns None)."""
    serial = str(serial or "").strip()
    if not SERIAL_RE.match(serial):
        raise BadNotes("That serial number doesn't look right.")
    entry: dict[str, Any] = {
        "bought": _date(bought, "Bought"),
        "warranty_until": _date(warranty_until, "Warranty until"),
        "note": clean_note(note),
        "temp_limit": _limit(temp_limit),
    }
    if entry["bought"] and entry["warranty_until"] and entry["warranty_until"] < entry["bought"]:
        raise BadNotes("The warranty can't end before the drive was bought.")
    entry = {k: v for k, v in entry.items() if v}
    with _lock:
        data = _load()
        if entry:
            if serial not in data and len(data) >= MAX_DRIVES:
                raise BadNotes("Too many drives have details already.")
            data[serial] = entry
        else:
            data.pop(serial, None)
        atomic_write_json(NOTES_FILE, data)
    return entry or None
