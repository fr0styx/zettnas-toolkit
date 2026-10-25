"""Host fan watchdog: keeps the fans safe when the ZettNAS app can't.

Runs in its own small container next to the app (see docs/FAN_WATCHDOG.md):

    python -m backend.fan_watchdog

It reads the app's heartbeat (backend/services/fan_heartbeat.py). When the beats stop for
FAN_WATCHDOG_STALE_SECS (default 30) without a clean release, the app was killed or hung while
it controlled the fans, and this process puts them in the same safe state the app uses on
shutdown: firmware control where the hardware has it, a fixed safe speed where it doesn't. It
acts once per outage and starts watching again when the beats come back."""

import json
import os
import time
from collections.abc import Callable
from typing import Any

STALE_SECS = float(os.environ.get("FAN_WATCHDOG_STALE_SECS", "30"))
CHECK_EVERY = float(os.environ.get("FAN_WATCHDOG_CHECK_SECS", "5"))
DRY_RUN = os.environ.get("FAN_WATCHDOG_DRY_RUN") == "1"  # log instead of touching the fans


def read_heartbeat(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "ts" in data else None


def needs_release(beat: dict[str, Any] | None, now: float, stale: float = STALE_SECS) -> bool:
    """True when the app was controlling the fans and stopped answering."""
    if not beat or beat.get("released"):
        return False
    try:
        return now - float(beat["ts"]) > stale
    except (TypeError, ValueError):
        return False


def _release() -> bool:
    if DRY_RUN:
        print("[fan-watchdog] dry run: would put the fans in their safe state now", flush=True)
        return True
    from backend.hardware.fans import failsafe_release_fans

    return bool(failsafe_release_fans(reason="watchdog: the app stopped answering"))


def controller() -> str:
    """Which fan controller this container can reach (for --check); never writes."""
    from backend.hardware.cpu import _find_hwmon
    from backend.hardware.fans import get_mmio_fan_controller

    hw = _find_hwmon()
    if hw:
        return f"hwmon {hw}"
    mmio = get_mmio_fan_controller()
    if mmio and mmio.is_available():
        return "embedded controller registers (/dev/mem)"
    return "none"


def watch(
    path: str,
    release: Callable[[], bool] = _release,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    rounds: int | None = None,
    log: Callable[[str], None] = print,
) -> int:
    """Checks the heartbeat every CHECK_EVERY seconds; returns how many times it released."""
    acted = False
    released = 0
    n = 0
    while rounds is None or n < rounds:
        n += 1
        beat = read_heartbeat(path)
        if needs_release(beat, clock()):
            if not acted:
                ok = release()
                released += 1
                acted = True
                log(
                    f"[fan-watchdog] the app stopped answering; fans put in their safe state ({'done' if ok else 'no fan controller found'})"
                )
        elif beat and not beat.get("released") and acted:
            acted = False
            log("[fan-watchdog] the app is answering again; watching")
        sleep(CHECK_EVERY)
    return released


def main(argv: list[str] | None = None) -> None:
    import sys

    from backend.services.fan_heartbeat import heartbeat_path

    path = heartbeat_path()
    if "--check" in (sys.argv[1:] if argv is None else argv):
        beat = read_heartbeat(path)
        print(f"fan controller: {controller()}")
        print(
            f"heartbeat: {path} "
            + (
                f"{time.time() - float(beat['ts']):.0f}s old, released={bool(beat.get('released'))}"
                if beat
                else "missing"
            )
        )
        return
    print(f"[fan-watchdog] watching {path} (safe state after {STALE_SECS:.0f}s without a beat)", flush=True)
    watch(path, log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
