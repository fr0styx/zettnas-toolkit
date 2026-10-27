"""
ZettNAS Toolkit - Unraid Telemetry Provider
Parses Unraid emhttp state (var.ini, mover.ini, disks.ini) for array status,
parity checks, mover progress, and storage subsystem health.
"""

import os
import time
from typing import Any

from backend.config import logger

_CACHED_UNRAID_STATUS: dict[str, Any] = {}
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


def _parse_ini_flat(filepath: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not os.path.isfile(filepath):
        return out
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
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


def read_unraid_status(force: bool = False) -> dict[str, Any]:
    global _CACHED_UNRAID_STATUS, _LAST_UNRAID_POLL
    now = time.time()
    if not force and _CACHED_UNRAID_STATUS and (now - _LAST_UNRAID_POLL < _CACHE_TTL):
        return _CACHED_UNRAID_STATUS

    emhttp_dir = _find_emhttp_dir()
    if not emhttp_dir:
        fallback: dict[str, Any] = {
            "available": False,
            "state": "STANDALONE",
            "color": "grey-off",
            "is_healthy": True,
            "disks": {"total": 0, "disabled": 0, "invalid": 0, "missing": 0, "new": 0},
            "parity_check": {
                "active": False,
                "paused": False,
                "action": "",
                "progress_pct": 0,
                "errors": 0,
                "speed": 0,
            },
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
    md_resync = _to_int("mdResync")

    # In Unraid, mdResyncAction, mdResyncPos, and mdResyncSize persist in var.ini indefinitely
    # after a parity check completes, pauses, or is cancelled.
    # An active sync is ONLY executing if mdState is STARTED and mdResync (sync speed in KB/s) > 0.
    has_md_resync = "mdResync" in var_data
    if has_md_resync:
        resync_active = bool(
            md_state == "STARTED"
            and md_resync > 0
            and resync_action
            and resync_action.strip()
            and resync_size > 0
            and resync_pos < resync_size
        )
    else:
        resync_active = bool(
            md_state == "STARTED"
            and resync_action
            and resync_action.strip()
            and resync_size > 0
            and resync_pos < resync_size
        )

    resync_paused = bool(
        md_state == "STARTED"
        and not resync_active
        and resync_action
        and resync_action.strip()
        and resync_size > 0
        and 0 < resync_pos < resync_size
    )
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

    res: dict[str, Any] = {
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
            "paused": resync_paused,
            "action": resync_action if (resync_active or resync_paused) else "",
            "progress_pct": resync_pct if (resync_active or resync_paused) else 0.0,
            "errors": resync_corr if (resync_active or resync_paused) else 0,
            "speed": md_resync if resync_active else 0,
        },
        # the last finished (or stopped) parity check: errors it found, when, and how it ended
        "last_parity_check": {
            "errors": _to_int("sbSyncErrs"),
            "finished_at": _to_int("sbSynced2") or None,
            "exit": _to_int("sbSyncExit", -1),
        },
        "mover": {
            "active": mover_active,
            "action": mover_action,
            "total_files": total_files,
            "remain_files": remain_files,
        },
        "parity_devices": [dev for dev, info in get_unraid_disk_roles().items() if info.get("is_parity")],
    }

    _CACHED_UNRAID_STATUS = res
    _LAST_UNRAID_POLL = now
    return res


_CACHED_UNRAID_ROLES: dict[str, dict[str, Any]] = {}
_LAST_UNRAID_ROLES_POLL = 0.0
_ROLES_CACHE_TTL = 5.0


def get_unraid_disk_roles(force: bool = False) -> dict[str, dict[str, Any]]:
    """
    Parses Unraid /var/local/emhttp/disks.ini to extract authoritative disk roles
    (e.g. Parity, Data, Cache, Boot) and parity labels.
    """
    global _CACHED_UNRAID_ROLES, _LAST_UNRAID_ROLES_POLL
    now = time.time()
    if not force and _CACHED_UNRAID_ROLES and (now - _LAST_UNRAID_ROLES_POLL < _ROLES_CACHE_TTL):
        return _CACHED_UNRAID_ROLES

    emhttp_dir = _find_emhttp_dir()
    if not emhttp_dir:
        return {}

    disks_file = os.path.join(emhttp_dir, "disks.ini")
    if not os.path.isfile(disks_file):
        return {}

    res: dict[str, dict[str, Any]] = {}
    cur_sec = None
    cur_data: dict[str, str] = {}
    try:
        with open(disks_file, encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if line.startswith("[") and line.endswith("]"):
                    if cur_sec and cur_data.get("device"):
                        dev = cur_data["device"].strip()
                        dtype = cur_data.get("type", "Data").strip()
                        is_parity = dtype.lower() == "parity" or cur_sec.lower().startswith("parity")
                        parity_lbl = "P2" if cur_sec.lower() == "parity2" else ("P" if is_parity else "")
                        res[dev] = {
                            "name": cur_sec,
                            "type": dtype,
                            "is_parity": is_parity,
                            "parity_label": parity_lbl,
                        }
                    cur_sec = line[1:-1].strip('"').strip("'")
                    cur_data = {}
                elif "=" in line:
                    key, val = line.split("=", 1)
                    cur_data[key.strip()] = val.strip().strip('"').strip("'")
            if cur_sec and cur_data.get("device"):
                dev = cur_data["device"].strip()
                dtype = cur_data.get("type", "Data").strip()
                is_parity = dtype.lower() == "parity" or cur_sec.lower().startswith("parity")
                parity_lbl = "P2" if cur_sec.lower() == "parity2" else ("P" if is_parity else "")
                res[dev] = {
                    "name": cur_sec,
                    "type": dtype,
                    "is_parity": is_parity,
                    "parity_label": parity_lbl,
                }
    except Exception as e:
        logger.debug(f"[Unraid] Error parsing disks.ini: {e}")

    _CACHED_UNRAID_ROLES = res
    _LAST_UNRAID_ROLES_POLL = now
    return res
