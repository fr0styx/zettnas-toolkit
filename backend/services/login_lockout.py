"""
File-backed login lockout shared across processes.

The rclone WebDAV/SFTP auth proxy runs as a fresh process for every login, so
an in-memory counter would never trip. Counters live in DATA_DIR and are
updated under an exclusive file lock.
"""

import fcntl
import json
import os
import time
from collections.abc import Callable
from typing import Any

FREE_ATTEMPTS = 5
MAX_LOCK_SECS = 15 * 60
FORGET_AFTER_SECS = 3600


def _path() -> str:
    from backend import config

    return os.path.join(getattr(config, "DATA_DIR", "/app/data"), "auth_lockout.json")


def _with_store(fn: Callable[[dict[str, Any]], tuple[Any, bool]]) -> Any:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "a+") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
            result, changed = fn(data)
            if changed:
                now = time.time()
                data = {k: v for k, v in data.items() if now - v.get("last_seen", 0) < FORGET_AFTER_SECS}
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.chmod(tmp, 0o600)
                os.replace(tmp, path)
            return result
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def remaining(key: str) -> int:
    """Seconds left on the lock for `key` (0 = not locked)."""

    def read(data):
        entry = data.get(key) or {}
        return max(0, int(entry.get("locked_until", 0) - time.time())), False

    try:
        return _with_store(read)
    except OSError:
        return 0


def register_failure(key: str) -> None:
    def bump(data):
        now = time.time()
        entry = data.setdefault(key, {"count": 0, "locked_until": 0.0, "last_seen": now})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["last_seen"] = now
        over = entry["count"] - FREE_ATTEMPTS
        if over >= 0:
            entry["locked_until"] = now + min(MAX_LOCK_SECS, 2**over * 5)
        return None, True

    try:
        _with_store(bump)
    except OSError:
        pass


def clear(key: str) -> None:
    def drop(data):
        return None, data.pop(key, None) is not None

    try:
        _with_store(drop)
    except OSError:
        pass
