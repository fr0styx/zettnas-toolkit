"""Whether Redfish answers (SET-01).

Redfish hands out the hardware inventory and live readings to monitoring tools. It used to be on
for every install, answer every signed-in account, and show its first page without sign-in. It is
off until an administrator turns it on.
"""

from __future__ import annotations

import os

from backend.config import DATA_DIR
from backend.fsutil import atomic_write_json, read_json

SETTINGS_FILE = os.path.join(DATA_DIR, "redfish.json")


def enabled() -> bool:
    return bool((read_json(SETTINGS_FILE, {}) or {}).get("enabled", False))


def set_enabled(on: bool) -> bool:
    atomic_write_json(SETTINGS_FILE, {"enabled": bool(on)})
    return bool(on)
