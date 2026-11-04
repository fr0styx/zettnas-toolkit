"""Card-slot changes from the kernel (PERF-18).

The kernel announces a card going in or out of the reader as a block-device uevent (the reader's
slots are polled by the kernel, see media_slots._ensure_slot_polling). While this listener runs,
the slots' size is read only after such an event, or every FALLBACK_S seconds in case one was
missed; without it (no netlink socket here), they are read on every pass as before.
"""

import socket
import threading
import time

from backend.config import logger

NETLINK_KOBJECT_UEVENT = 15
FALLBACK_S = 30.0

_state = {"listening": False, "changed": 0.0}
_lock = threading.Lock()


def parse(msg: bytes) -> dict[str, str]:
    """A kernel uevent ("change@/devices/...\\0ACTION=change\\0SUBSYSTEM=block\\0...") as fields."""
    out: dict[str, str] = {}
    for part in msg.split(b"\0"):
        text = part.decode("utf-8", "replace")
        if "=" in text:
            k, v = text.split("=", 1)
            out[k] = v
    return out


def relevant(ev: dict[str, str]) -> bool:
    """A SCSI disk appearing, going or changing media (a card reader's slot is one)."""
    return (
        ev.get("SUBSYSTEM") == "block"
        and ev.get("ACTION") in ("add", "remove", "change")
        and ev.get("DEVNAME", "").startswith("sd")
    )


def mark_changed() -> None:
    with _lock:
        _state["changed"] = time.monotonic()


def listening() -> bool:
    return bool(_state["listening"])


def should_probe(last_probe: float, now: float | None = None) -> bool:
    """Whether to read a slot's size again, given when it was last read (time.monotonic())."""
    if not _state["listening"] or not last_probe:
        return True
    now = time.monotonic() if now is None else now
    with _lock:
        changed = _state["changed"]
    return changed >= last_probe or now - last_probe >= FALLBACK_S


def _listen(sock: socket.socket) -> None:
    while True:
        try:
            data = sock.recv(65536)
        except OSError:
            logger.debug("[media_events] uevent socket closed; reading the slots on every pass again")
            _state["listening"] = False
            return
        if relevant(parse(data)):
            mark_changed()


def start() -> bool:
    """Starts the listener once; False when this host or container offers no uevent socket."""
    with _lock:
        if _state["listening"]:
            return True
        try:
            sock = socket.socket(socket.AF_NETLINK, socket.SOCK_DGRAM, NETLINK_KOBJECT_UEVENT)
            sock.bind((0, 1))  # group 1: the kernel's own events
        except (OSError, AttributeError):
            logger.debug("[media_events] no uevent socket; the slots are read on every pass")
            return False
        _state["listening"] = True
        _state["changed"] = time.monotonic()
    threading.Thread(target=_listen, args=(sock,), name="media-uevents", daemon=True).start()
    return True
