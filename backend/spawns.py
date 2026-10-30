"""Counts the processes the backend starts, and who started them (NPERF-1).

Most of the backend's idle CPU has been the tools it runs (smartctl, zpool, docker, ip): a call of
20-200 ms that an outside sampler, listing processes once a second, never sees. Counting inside
the app sees every one: subprocess.run, Popen and asyncio's subprocesses all go through
subprocess.Popen, which install() wraps. The counts, by the backend module that asked, are in
/api/metrics as zettnas_process_spawns_total, which the hardware budget check reads when it can.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections import Counter

_ORIGINAL = subprocess.Popen
_counts: Counter[str] = Counter()
_lock = threading.Lock()
# frames of these modules are the plumbing between a caller and Popen, not the caller
PLUMBING = ("subprocess", "asyncio", "concurrent", "threading", "backend.proc", "backend.spawns", "contextlib")


def caller(depth: int = 2) -> str:
    """The module that started the process: the first frame outside the plumbing."""
    frame = sys._getframe(depth)  # noqa: SLF001 (cheap, once per process started)
    while frame is not None:
        name = frame.f_globals.get("__name__", "")
        if not name.startswith(PLUMBING):
            return name or "?"
        frame = frame.f_back
    return "?"


def note(who: str) -> None:
    with _lock:
        _counts[who] += 1


class CountedPopen(_ORIGINAL):  # type: ignore[misc, valid-type]
    """subprocess.Popen that counts each process it starts."""

    def __init__(self, *args, **kwargs):
        note(caller())
        super().__init__(*args, **kwargs)


def install() -> None:
    """Counts every process started from now on (idempotent)."""
    subprocess.Popen = CountedPopen  # type: ignore[misc]


def counts() -> dict[str, int]:
    with _lock:
        return dict(_counts)


def total() -> int:
    with _lock:
        return sum(_counts.values())


def prometheus() -> str:
    """The counts in Prometheus' text format."""
    lines = [
        "# HELP zettnas_process_spawns_total Processes the backend started, by the module that started them",
        "# TYPE zettnas_process_spawns_total counter",
    ]
    for who, n in sorted(counts().items()):
        lines.append(f'zettnas_process_spawns_total{{caller="{who}"}} {n}')
    return "\n".join(lines) + "\n"
