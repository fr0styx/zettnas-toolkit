"""Talking to the hardware helper (SEC-24 step 2, backend/hw_helper.py) when it runs.

The helper answers on a Unix socket in Kiboto's data folder (hw/hw.sock, shared with its container).
When it answers, the fans and the front button go through it and Kiboto needs no /dev/mem of its own;
when it doesn't (no helper, an install from before), callers use /dev/mem as they always did.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger

SOCKET_PATH = os.path.join(DATA_DIR, "hw", "hw.sock")
TIMEOUT = 1.0
RECHECK = 30.0  # seconds a "not there" is remembered, so a missing helper costs nothing per call

_lock = threading.Lock()
_seen: dict[str, float] = {"at": 0.0, "up": 0.0}


class HelperError(RuntimeError):
    """The helper refused the request or didn't answer."""


def call(op: str, **fields: Any) -> dict[str, Any]:
    """One request; raises HelperError when the helper isn't there or says no."""
    req = json.dumps({"op": op, **fields}).encode() + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(TIMEOUT)
            s.connect(SOCKET_PATH)
            s.sendall(req)
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
    except OSError as e:
        raise HelperError(f"the hardware helper didn't answer: {e}") from e
    try:
        reply = json.loads(buf)
    except ValueError as e:
        raise HelperError("the hardware helper sent nonsense") from e
    if not isinstance(reply, dict) or reply.get("error"):
        raise HelperError(str(reply.get("error") if isinstance(reply, dict) else "bad reply"))
    return reply


def available(force: bool = False) -> bool:
    """Whether the helper answers (checked at most every RECHECK seconds)."""
    now = time.monotonic()
    with _lock:
        if not force and now - _seen["at"] < RECHECK:
            return bool(_seen["up"])
    up = False
    if os.path.exists(SOCKET_PATH):
        try:
            up = bool(call("ping").get("ok"))
        except HelperError as e:
            logger.debug("[hw-helper] %s", e)
    with _lock:
        _seen.update(at=now, up=float(up))
    return up


def forget() -> None:
    """Ask again at the next call (after the helper was started or stopped)."""
    with _lock:
        _seen.update(at=0.0, up=0.0)
