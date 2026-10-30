"""Every drive ZettNAS has seen, by serial number: so a drive that was taken out still has a
record (model, size, its last verdict, when it was last seen) next to its warranty details, and
an owner can see what left the box and when. A drive put back in is simply present again.

Written from Drive Health's list, only when something changed or once an hour, so opening the
window stays cheap.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

SEEN_FILE = os.path.join(DATA_DIR, "drive_seen.json")
TOUCH_SECS = 3600
MAX_DRIVES = 500
KEPT = ("serial", "model", "dev", "role", "capacity_bytes", "verdict", "label", "label_key")
_lock = threading.Lock()


def _key(serial: Any) -> str:
    s = str(serial or "").strip()
    return "" if not s or "standby" in s.lower() or s.lower() in ("unknown", "n/a") else s.upper()


def _load() -> dict[str, dict[str, Any]]:
    try:
        with open(SEEN_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        logger.warning("drive_registry: %s could not be read; starting empty", SEEN_FILE, exc_info=True)
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def note_present(drives: list[dict[str, Any]], now: float | None = None) -> bool:
    """Records the drives in Drive Health's list; True when the file was written."""
    now = time.time() if now is None else now
    with _lock:
        data = _load()
        changed = False
        for d in drives or []:
            key = _key(d.get("serial"))
            if not key:
                continue
            old = data.get(key) or {}
            new = {**old, **{k: d.get(k) for k in KEPT if d.get(k) not in (None, "")}}
            if d.get("verdict") == "unknown" and old.get("verdict"):  # not read yet: keep what it was
                for k in ("verdict", "label", "label_key"):
                    if k in old:
                        new[k] = old[k]
                    else:
                        new.pop(k, None)
            new.setdefault("first_seen", int(now))
            if new != old or now - float(old.get("last_seen") or 0) >= TOUCH_SECS:
                if key not in data and len(data) >= MAX_DRIVES:
                    continue
                new["last_seen"] = int(now)
                data[key] = new
                changed = True
        if changed:
            try:
                atomic_write_json(SEEN_FILE, data)
            except OSError:
                logger.warning("drive_registry: could not write %s", SEEN_FILE, exc_info=True)
                return False
    return changed


def taken_out(present_serials: list[str]) -> list[dict[str, Any]]:
    """The drives seen before that aren't in the box now, last seen first."""
    here = {_key(s) for s in present_serials or []}
    with _lock:
        data = _load()
    gone = [v for k, v in data.items() if k not in here]
    return sorted(gone, key=lambda v: -float(v.get("last_seen") or 0))


def forget(serial: str) -> bool:
    """Drops a drive's record; True when there was one."""
    key = _key(serial)
    with _lock:
        data = _load()
        if key not in data:
            return False
        del data[key]
        atomic_write_json(SEEN_FILE, data)
    return True
