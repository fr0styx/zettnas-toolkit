"""Safer defaults for new installs, without changing what existing families rely on (B11, D1).

A new install starts with the safe defaults: nobody but the owner and admins can reach a share
until they are given it, and the Auditor role reads system status only. An install upgraded
from an earlier version keeps its behaviour: the settings it relied on implicitly are written
down explicitly once, and the Security Advisor offers a one-click fix for each of them.

Whether the install is new is decided once, from whether users.db existed before this start.
"""

from __future__ import annotations

import os
import time

from backend import config
from backend.fsutil import atomic_write_json, locked_json, read_json

MARKER = ".install-defaults-b11"
SAFE_AUDITOR_SCOPES = ["system:view", "hardware:read", "logs:read", "audit:read", "storage:read"]


def _marker() -> str:
    return os.path.join(config.DATA_DIR, MARKER)


def is_existing_install() -> bool:
    """True when this data folder came from a version before the B11 defaults."""
    data = read_json(_marker(), {}) or {}
    return bool(data.get("existing"))


def apply_once(existing_install: bool) -> bool:
    """Records whether this install is new or upgraded, once. For an upgraded install the share
    access it relied on (everyone may use every share) is written down explicitly, so the new
    safe default for a missing setting never applies to it. Returns True when it ran now."""
    path = _marker()
    if os.path.exists(path):
        return False
    if existing_install:
        from backend.services import share_access

        with locked_json(share_access._file()):
            cfg = read_json(share_access._file(), {}) or {}
            if "default_level" not in cfg:
                cfg["default_level"] = "write"  # what upgraded installs have always had
                atomic_write_json(share_access._file(), cfg)
        share_access.invalidate()
    atomic_write_json(path, {"existing": bool(existing_install), "at": time.time()})
    return True
