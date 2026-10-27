"""
Supervised background threads (ARC-02).

A daemon that crashes is logged with its traceback and restarted, waiting 1 s, then
2, 4, … up to 60 s between attempts (the wait resets after it has run for 10 minutes).
A daemon that returns normally (e.g. no LCD fitted) is marked "stopped" and left alone.
daemon_status() reports each one for /api/health and diagnostics.

A daemon that loops calls beat() each time round (REL-18). One that was started with
beat_every and has not beaten for three of its intervals (at least a minute) is "stalled":
it is still running but stuck, which a crash counter alone never shows.
"""

import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("ZettNAS")

_lock = threading.Lock()
_daemons: dict[str, dict[str, Any]] = {}
MAX_BACKOFF_S = 60.0
STABLE_AFTER_S = 600.0


def supervise(
    name: str,
    target: Callable[..., Any],
    *args: Any,
    restart: bool = True,
    beat_every: float | None = None,
    _sleep=time.sleep,
) -> threading.Thread:
    """Starts target(*args) in a supervised daemon thread named `name`. With beat_every (seconds),
    the daemon is expected to call beat() that often."""
    with _lock:
        _daemons[name] = {
            "state": "starting",
            "restarts": 0,
            "last_error": "",
            "started_at": time.time(),
            "beat_every": beat_every,
            "last_beat": None,
        }

    def runner() -> None:
        backoff = 1.0
        while True:
            started = time.time()
            with _lock:
                _daemons[name].update(state="running", started_at=started)
            try:
                target(*args)
            except Exception as e:  # supervised: log and restart below
                err = f"{type(e).__name__}: {e}"
                logger.error(f"[Supervisor] {name} crashed: {err}\n{traceback.format_exc()}")
                with _lock:
                    _daemons[name].update(state="crashed", last_error=err[:500])
                if not restart:
                    return
                if time.time() - started > STABLE_AFTER_S:
                    backoff = 1.0
                with _lock:
                    _daemons[name]["restarts"] += 1
                _sleep(backoff)
                backoff = min(MAX_BACKOFF_S, backoff * 2)
                continue
            with _lock:
                _daemons[name].update(state="stopped")
            return

    t = threading.Thread(target=runner, name=name, daemon=True)
    t.start()
    return t


def beat(name: str | None = None, now: float | None = None) -> None:
    """The calling daemon is alive and going round its loop (REL-18)."""
    key = name or threading.current_thread().name
    with _lock:
        if key in _daemons:
            _daemons[key]["last_beat"] = now or time.time()


def stalled_after(beat_every: float) -> float:
    return max(3 * beat_every, beat_every + 60.0)


def daemon_status(now: float | None = None) -> dict[str, dict[str, Any]]:
    now = now or time.time()
    out = {}
    with _lock:
        for k, v in _daemons.items():
            d = dict(v)
            every = d.get("beat_every")
            if d["state"] == "running" and every:
                since = now - float(d.get("last_beat") or d.get("started_at") or now)
                d["beat_age"] = round(since, 1)
                if since > stalled_after(float(every)):
                    d["state"] = "stalled"
            out[k] = d
    return out


def stalled() -> list[str]:
    return sorted(k for k, v in daemon_status().items() if v["state"] == "stalled")


def install_os_thread_names() -> bool:
    """Gives every Python thread its name at the OS level (/proc/<pid>/task/<tid>/comm), so
    top, ps and diagnostics show "StatsCollector" instead of "python3" (audit PERF-5)."""
    try:
        import ctypes

        libc = ctypes.CDLL(None)
        prctl = libc.prctl
    except (OSError, AttributeError):
        return False
    original = getattr(threading.Thread, "run", None)
    if original is None:
        return False  # threading.Thread replaced (tests)
    if getattr(original, "_zn_named", False):
        return True

    def run(self):  # type: ignore[no-untyped-def]
        try:
            prctl(15, self.name.encode("utf-8", "replace")[:15], 0, 0, 0)  # PR_SET_NAME
        except Exception:
            logger.debug("supervisor: thread name not set", exc_info=True)
        return original(self)

    run._zn_named = True  # type: ignore[attr-defined]
    threading.Thread.run = run  # type: ignore[method-assign]
    return True
