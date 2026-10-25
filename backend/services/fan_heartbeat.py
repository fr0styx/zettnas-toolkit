"""The app's side of the host fan watchdog: a heartbeat in the host's /dev/shm.

While ZettNAS controls the fans it rewrites a tiny file every few seconds. If the app is killed
(SIGKILL, out of memory, a crash) the beats stop with "released": false, and the watchdog,
running in its own container, puts the fans in their safe state. A clean shutdown writes a last
beat with "released": true. /dev/shm is memory: the beats never wake a disk."""

import os
import time

from backend.config import HOST_DEV, logger
from backend.fsutil import atomic_write_json

BEAT_EVERY = 5.0
_last = 0.0


def heartbeat_path() -> str:
    return os.environ.get("FAN_WATCHDOG_HEARTBEAT") or os.path.join(HOST_DEV, "shm", "zettnas-fan-heartbeat.json")


def beat(released: bool = False, now: float | None = None, force: bool = False) -> bool:
    """Writes a beat (at most every BEAT_EVERY seconds unless forced). False when it can't."""
    global _last
    now = time.time() if now is None else now
    if not force and now - _last < BEAT_EVERY:
        return True
    try:
        atomic_write_json(heartbeat_path(), {"ts": now, "released": bool(released), "pid": os.getpid()})
    except OSError:
        logger.debug("fan heartbeat not written", exc_info=True)
        return False
    _last = now
    return True
