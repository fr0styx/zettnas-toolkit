"""Short external commands with a time limit (ARC-21).

A command that hangs (an umount on a dead mount, a tool waiting on a device) must not hold a
worker thread forever. run_bounded() always passes a timeout; when it runs out the command
counts as failed, with exit code 124 like timeout(1), and a warning is logged.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any

from backend.config import logger

TIMED_OUT = 124


def run_bounded(cmd: Sequence[str], *, timeout: float, **kwargs: Any) -> subprocess.CompletedProcess:
    """subprocess.run with a required timeout; a hang returns exit code 124 instead of raising."""
    try:
        return subprocess.run(list(cmd), timeout=timeout, **kwargs)  # noqa: S603 (callers pass fixed tools)
    except subprocess.TimeoutExpired as e:
        logger.warning(f"[proc] {cmd[0]} did not finish within {timeout:g} s; treated as failed")
        empty = "" if kwargs.get("text") or kwargs.get("encoding") else b""
        return subprocess.CompletedProcess(list(cmd), TIMED_OUT, e.stdout or empty, e.stderr or empty)
