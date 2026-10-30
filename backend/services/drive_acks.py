"""Drive Health: "I know about this one". The owner can acknowledge a finding that is worth
watching or means "replace soon" (8 replaced sectors that haven't moved in a year, an old drive):
it then no longer sets the drive's verdict, so the drive reads Healthy again and no alert or
reminder is sent for it.

The acknowledgement is for that finding with those numbers. When the numbers change (the count
grows), the finding is back, the verdict rises and the owner is alerted as before. Findings that
mean "replace now" (a failed self-test, the drive reporting it is failing) can't be acknowledged.

Kept by serial number in the data folder, like the purchase and warranty details.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json
from backend.services.drive_notes import SERIAL_RE, BadNotes

ACKS_FILE = os.path.join(DATA_DIR, "drive_acks.json")
ACKABLE = ("watch", "soon")
MAX_PER_DRIVE = 50
_lock = threading.Lock()


def fingerprint(code: str, params: dict[str, Any] | None) -> str:
    """A finding with its numbers: "reallocated_stable:{"n": 8}"."""
    return f"{code}:{json.dumps(params or {}, sort_keys=True, separators=(',', ':'))}"


def _key(serial: Any) -> str:
    return str(serial or "").strip().upper()


def _load() -> dict[str, dict[str, dict[str, Any]]]:
    try:
        with open(ACKS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("drive_acks: %s could not be read; starting empty", ACKS_FILE, exc_info=True)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def acks_for(*serials: Any) -> dict[str, dict[str, Any]]:
    """The acknowledged findings of a drive, by fingerprint (any of its serial spellings)."""
    keys = {_key(s) for s in serials if _key(s)}
    if not keys:
        return {}
    with _lock:
        data = _load()
    out: dict[str, dict[str, Any]] = {}
    for k in keys:
        out.update(data.get(k) or {})
    return out


def all_acks() -> dict[str, dict[str, dict[str, Any]]]:
    with _lock:
        return _load()


def acknowledge(serial: str, code: str, params: dict[str, Any] | None, severity: str, title: str = "") -> str:
    """Remembers that the owner knows about this finding; returns its fingerprint."""
    if not SERIAL_RE.match(str(serial or "").strip()):
        raise BadNotes("That serial number doesn't look right.")
    if severity not in ACKABLE:
        raise BadNotes("Only findings to watch or to plan for can be acknowledged, not ones that say replace now.")
    if not str(code or "").replace("_", "").isalnum() or len(code) > 64:
        raise BadNotes("Unknown finding.")
    fp = fingerprint(code, params)
    if len(fp) > 400:
        raise BadNotes("Unknown finding.")
    with _lock:
        data = _load()
        mine = data.setdefault(_key(serial), {})
        if fp not in mine and len(mine) >= MAX_PER_DRIVE:
            raise BadNotes("This drive has too many acknowledged findings.")
        # an older acknowledgement of the same finding, with other numbers, no longer applies
        for old in [f for f in mine if f.split(":", 1)[0] == code and f != fp]:
            del mine[old]
        mine[fp] = {"at": int(time.time()), "severity": severity, "title": str(title or "")[:200]}
        atomic_write_json(ACKS_FILE, data)
    return fp


def forget(serial: str, code: str) -> bool:
    """Takes back the acknowledgement of a drive's finding; True when there was one."""
    with _lock:
        data = _load()
        mine = data.get(_key(serial)) or {}
        gone = [f for f in mine if f.split(":", 1)[0] == code]
        if not gone:
            return False
        for f in gone:
            del mine[f]
        if not mine:
            data.pop(_key(serial), None)
        atomic_write_json(ACKS_FILE, data)
    return True


def apply_acks(result: dict[str, Any], *serials: Any) -> dict[str, Any]:
    """The verdict with the owner's acknowledged findings set aside: each keeps its text, is marked
    "acknowledged" (when, and how severe it was) and counts as fine. A result that was worked out
    earlier is brought up to date both ways, so taking an acknowledgement back shows it again."""
    findings = result.get("findings") or []
    if not findings:
        return result
    acks = acks_for(*serials)
    from backend.services import drive_health

    changed = False
    out = []
    for f in findings:
        had = f.get("acknowledged")
        ack = acks.get(fingerprint(f.get("code", ""), f.get("params")))
        if had and not ack:
            f = {k: v for k, v in f.items() if k != "acknowledged"} | {"severity": had.get("severity", "watch")}
            changed = True
        elif ack and not had and f.get("severity") in ACKABLE:
            f = {**f, "severity": "ok", "acknowledged": {"at": ack.get("at"), "severity": f["severity"]}}
            changed = True
        out.append(f)
    if not changed:
        return result
    out.sort(key=lambda f: -drive_health.ORDER[f["severity"]])
    return {**result, **drive_health.summarize(out)}
