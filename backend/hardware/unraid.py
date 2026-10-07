"""
ZettNAS Toolkit - Unraid Telemetry Provider
Parses Unraid emhttp state (var.ini, mover.ini, disks.ini) for array status,
parity checks, mover progress, and storage subsystem health.
"""

import os
import time
from typing import Any, Dict

from backend.config import logger

_CACHED_UNRAID_STATUS: Dict[str, Any] = {}
_LAST_UNRAID_POLL = 0.0
_CACHE_TTL = 1.5


def _find_emhttp_dir() -> str | None:
    custom = os.getenv("UNRAID_EMHTTP_DIR", "").strip()
    if custom:
        return custom if (os.path.isdir(custom) and os.path.exists(os.path.join(custom, "var.ini"))) else None
    candidates = [
        "/var/local/emhttp",
        "/host/var/local/emhttp",
    ]
    for c in candidates:
        if c and os.path.isdir(c) and os.path.exists(os.path.join(c, "var.ini")):
            return c
    return None


def _parse_ini_flat(filepath: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isfile(filepath):
        return out
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    k = key.strip()
                    v = val.strip().strip('"').strip("'")
                    out[k] = v
    except Exception as e:
        logger.debug(f"[Unraid] Error parsing {filepath}: {e}")
    return out


def read_unraid_status(force: bool = False) -> Dict[str, Any]:
    global _CACHED_UNRAID_STATUS, _LAST_UNRAID_POLL
    now = time.time()
    if not force and _CACHED_UNRAID_STATUS and (now - _LAST_UNRAID_POLL < _CACHE_TTL):
        return _CACHED_UNRAID_STATUS

    emhttp_dir = _find_emhttp_dir()
    if not emhttp_dir:
        fallback: Dict[str, Any] = {
            "available": False,
            "state": "STANDALONE",
            "color": "grey-off",
            "is_healthy": True,
            "disks": {"total": 0, "disabled": 0, "invalid": 0, "missing": 0, "new": 0},
            "parity_check": {"active": False, "action": "", "progress_pct": 0, "errors": 0},
            "mover": {"active": False, "action": "", "total_files": 0, "remain_files": 0},
        }
        _CACHED_UNRAID_STATUS = fallback
        _LAST_UNRAID_POLL = now
        return fallback

    var_file = os.path.join(emhttp_dir, "var.ini")
    var_data = _parse_ini_flat(var_file)
    if not var_data or "mdState" not in var_data:
        # Atomic read guard: emhttp rewrites var.ini dynamically. Retry after brief backoff.
        time.sleep(0.05)
        var_data = _parse_ini_flat(var_file)
        if (not var_data or "mdState" not in var_data) and _CACHED_UNRAID_STATUS:
            return _CACHED_UNRAID_STATUS
    mover_data = _parse_ini_flat(os.path.join(emhttp_dir, "mover.ini"))

    version = var_data.get("version", "")
    server_name = var_data.get("NAME", "")
    model = var_data.get("SYS_MODEL", "")
    md_state = var_data.get("mdState", "UNKNOWN")
    fs_state = var_data.get("fsState", "UNKNOWN")
    color = var_data.get("mdColor", "grey-off")

    def _to_int(k: str, default: int = 0) -> int:
        val = var_data.get(k, "")
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    num_disks = _to_int("mdNumDisks")
    num_disabled = _to_int("mdNumDisabled")
    num_invalid = _to_int("mdNumInvalid")
    num_missing = _to_int("mdNumMissing")
    num_new = _to_int("mdNumErased")

    resync_action = var_data.get("mdResyncAction", "")
    resync_pos = _to_int("mdResyncPos")
    resync_size = _to_int("mdResyncSize")
    resync_corr = _to_int("mdResyncCorr")
    resync_active = bool(resync_action and resync_action.strip() and resync_size > 0 and resync_pos < resync_size)
    resync_pct = round((resync_pos / resync_size) * 100, 1) if resync_size > 0 else 0.0

    mover_active = var_data.get("shareMoverActive", "no").lower() == "yes"
    mover_action = mover_data.get("Action", "")

    def _mover_int(k: str) -> int:
        val = mover_data.get(k, "")
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    total_files = _mover_int("TotalFilesToSecondary") + _mover_int("TotalFilesFromSecondary")
    remain_files = _mover_int("RemainFilesToSecondary") + _mover_int("RemainFilesFromSecondary")

    res: Dict[str, Any] = {
        "available": True,
        "version": version,
        "server_name": server_name,
        "model": model,
        "state": md_state,
        "fs_state": fs_state,
        "color": color,
        "is_healthy": color.startswith("green"),
        "disks": {
            "total": num_disks,
            "disabled": num_disabled,
            "invalid": num_invalid,
            "missing": num_missing,
            "new": num_new,
        },
        "parity_check": {
            "active": resync_active,
            "action": resync_action,
            "progress_pct": resync_pct,
            "errors": resync_corr,
        },
        "mover": {
            "active": mover_active,
            "action": mover_action,
            "total_files": total_files,
            "remain_files": remain_files,
        },
    }

    _CACHED_UNRAID_STATUS = res
    _LAST_UNRAID_POLL = now
    return res
