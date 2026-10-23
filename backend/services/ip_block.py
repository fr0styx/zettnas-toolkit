"""
IP block-list (M5).

An address is blocked for a while when it keeps failing to sign in (web or WebDAV),
or at once when the ransomware guard sees an attack from it. Blocked addresses get
403 on the web app and WebDAV, and are listed under `hosts deny` in ZettNAS's own
Samba config. Loopback and the addresses in ZETTNAS_TRUSTED_IPS are never blocked,
so the admin can't lock themselves out of the console.
"""

import ipaddress
import json
import os
import threading
import time
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json

STORE = os.path.join(DATA_DIR, "ip_blocks.json")
FAIL_WINDOW_S = 15 * 60
FAIL_LIMIT = 20
FAIL_BLOCK_S = 60 * 60
_lock = threading.Lock()
_failures: dict[str, list[float]] = {}
_cache: dict[str, Any] = {"loaded": False, "blocks": {}}


def _trusted(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True  # not an address we can block ("unknown", test clients)
    if addr.is_loopback:
        return True
    for entry in filter(None, (x.strip() for x in os.environ.get("ZETTNAS_TRUSTED_IPS", "").split(","))):
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _load() -> dict[str, dict[str, Any]]:
    if not _cache["loaded"]:
        try:
            with open(STORE, encoding="utf-8") as f:
                data = json.load(f)
            _cache["blocks"] = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _cache["blocks"] = {}
        _cache["loaded"] = True
    return _cache["blocks"]


def _save(blocks: dict[str, dict[str, Any]]) -> None:
    try:
        atomic_write_json(STORE, blocks, indent=1)
    except OSError:
        logger.warning("[IPBlock] Could not save the block-list", exc_info=True)


def block(ip: str, reason: str, seconds: int | None = FAIL_BLOCK_S) -> bool:
    """Blocks ip for `seconds` (None: until unblocked). Returns False for trusted addresses."""
    if not ip or _trusted(ip):
        return False
    with _lock:
        blocks = _load()
        blocks[ip] = {"reason": reason[:200], "since": time.time(), "until": time.time() + seconds if seconds else None}
        _save(blocks)
    logger.warning(f"[IPBlock] Blocked {ip}: {reason}")
    try:
        from backend.state import add_event

        add_event("security", f"Blocked {ip}: {reason}", "warning")
    except Exception:
        logger.debug("ip_block.block: event log unavailable", exc_info=True)
    _sync_samba()
    return True


def unblock(ip: str) -> bool:
    with _lock:
        blocks = _load()
        found = blocks.pop(ip, None) is not None
        if found:
            _save(blocks)
    if found:
        _sync_samba()
    return found


def is_blocked(ip: str) -> bool:
    if not ip:
        return False
    with _lock:
        entry = _load().get(ip)
        if not entry:
            return False
        if entry.get("until") and entry["until"] < time.time():
            blocks = _load()
            blocks.pop(ip, None)
            _save(blocks)
            return False
    return True


def list_blocks() -> list[dict[str, Any]]:
    now = time.time()
    with _lock:
        return [{"ip": ip, **e} for ip, e in sorted(_load().items()) if not e.get("until") or e["until"] > now]


def record_auth_failure(ip: str, service: str = "web") -> bool:
    """Counts a failed sign-in; blocks the address after FAIL_LIMIT in FAIL_WINDOW_S. True if it was blocked now."""
    if not ip or _trusted(ip):
        return False
    now = time.time()
    with _lock:
        hits = [t for t in _failures.get(ip, []) if now - t < FAIL_WINDOW_S] + [now]
        _failures[ip] = hits
        if len(_failures) > 5000:
            for k in [k for k, v in _failures.items() if now - v[-1] > FAIL_WINDOW_S]:
                _failures.pop(k, None)
    if len(hits) >= FAIL_LIMIT:
        _failures.pop(ip, None)
        return block(ip, f"{len(hits)} failed {service} sign-ins in {FAIL_WINDOW_S // 60} minutes")
    return False


def _sync_samba() -> None:
    try:
        from backend.services.samba_engine import get_samba_engine

        eng = get_samba_engine()
        eng.generate_and_save_conf()
        eng.reload_service()
    except Exception:
        logger.debug("ip_block._sync_samba: Samba not managed here", exc_info=True)


def _reset_for_tests() -> None:
    with _lock:
        _failures.clear()
        _cache.update(loaded=True, blocks={})


if __name__ == "__main__":
    # docker exec zettnas-toolkit python3 -m backend.services.ip_block --unblock 192.168.1.50
    import sys

    if len(sys.argv) == 3 and sys.argv[1] == "--unblock":
        print("unblocked" if unblock(sys.argv[2]) else "not blocked")
    else:
        for b in list_blocks():
            print(b["ip"], b.get("reason", ""))
