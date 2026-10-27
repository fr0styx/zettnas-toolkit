"""Who gets the GPU first (PERF-1, AI-14): chat, then search, then indexing, then photo reading.

A home server has one small GPU (often an iGPU) shared by the chat model, the embedder and the
vision model. A GPU cannot be taken back from a job that is running, so the order is kept
between jobs: work that someone is waiting for never waits, and background work starts its next
piece only when nothing ahead of it is running.

- CHAT: a reply someone is reading. Never waits.
- QUERY: embedding a search question. Never waits.
- INDEX: embedding files. Each batch waits while a chat reply or a search runs, at most
  MAX_WAIT_SECS, so indexing is slowed but never stopped.
- VISION: captions and text from photos and scans. Does not start while anything else runs
  (vision_queue.system_idle), and also waits two minutes after the last chat.

    with gpu_queue.use(gpu_queue.QUERY):
        ...embed the question...

    gpu_queue.wait_turn(gpu_queue.INDEX)
    with gpu_queue.use(gpu_queue.INDEX):
        ...embed a batch...
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

CHAT, QUERY, INDEX, VISION = 0, 1, 2, 3
NAMES = ("chat", "query", "index", "vision")
MAX_WAIT_SECS = 30.0

_cond = threading.Condition()
_running = [0, 0, 0, 0]
_waited = {"count": 0, "secs": 0.0}

F = TypeVar("F", bound=Callable[..., Any])


@contextmanager
def use(kind: int) -> Iterator[None]:
    """Marks a job of this kind as running on the GPU for the duration of the block."""
    with _cond:
        _running[kind] += 1
    try:
        yield
    finally:
        with _cond:
            _running[kind] -= 1
            _cond.notify_all()


def holds(kind: int) -> Callable[[F], F]:
    """The decorator form of use()."""

    def wrap(fn: F) -> F:
        @functools.wraps(fn)
        def inner(*a: Any, **k: Any) -> Any:
            with use(kind):
                return fn(*a, **k)

        return inner  # type: ignore[return-value]

    return wrap


def ahead_of(kind: int) -> bool:
    """Whether a job that comes before this kind is running now."""
    with _cond:
        return any(_running[k] for k in range(kind))


def wait_turn(kind: int, max_wait: float = MAX_WAIT_SECS) -> float:
    """Waits until nothing ahead of this kind runs, or max_wait passed. Returns the seconds waited."""
    if kind <= QUERY:
        return 0.0
    start = time.monotonic()
    with _cond:
        while any(_running[k] for k in range(kind)):
            left = max_wait - (time.monotonic() - start)
            if left <= 0:
                break
            _cond.wait(left)
        waited = time.monotonic() - start
        if waited > 0.001:
            _waited["count"] += 1
            _waited["secs"] += waited
    return waited


def snapshot() -> dict[str, Any]:
    """What runs now, and how often and how long background work waited (for the health page)."""
    with _cond:
        return {
            "running": {NAMES[k]: _running[k] for k in range(len(NAMES))},
            "waits": _waited["count"],
            "waited_secs": round(_waited["secs"], 1),
        }
