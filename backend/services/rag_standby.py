"""
Standby guard for the AI index: which disks hold a path and whether they sleep
(AI-08), without waking them.

Split out of rag_engine.py (AI-21), which re-exports these names.
"""

import os
import re
import subprocess
import time
from typing import Any

from backend.config import logger
from backend.ignored_errors import ignored
from backend.state import Z_STATE

_UNRAID_INI_CACHE: dict[str, Any] = {"ts": 0.0, "disks": {}, "shares": {}}
_SMARTCTL_STANDBY_CACHE: dict[str, tuple[float, bool]] = {}


def _parse_ini_sections(ini_path: str) -> dict[str, dict[str, str]]:
    """Parses Unraid emhttp .ini files (disks.ini, shares.ini) from RAM tmpfs without disk I/O."""
    result: dict[str, dict[str, str]] = {}
    if not os.path.isfile(ini_path):
        return result
    try:
        with open(ini_path, encoding="utf-8", errors="replace") as f:
            current_sec: str | None = None
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("[") and line.endswith("]"):
                    sec_name = line[1:-1].strip().strip('"').strip("'")
                    current_sec = sec_name
                    if current_sec not in result:
                        result[current_sec] = {}
                elif current_sec is not None and "=" in line:
                    k, v = line.split("=", 1)
                    result[current_sec][k.strip()] = v.strip().strip('"')
    except Exception:
        ignored("backend.services.rag_engine._parse_ini_sections")
    return result


def _get_unraid_disks_and_shares() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    """Returns cached (disks_dict, shares_dict) from /var/local/emhttp/{disks,shares}.ini."""
    now = time.time()
    if (now - float(_UNRAID_INI_CACHE.get("ts", 0.0))) < 1.5:
        return (_UNRAID_INI_CACHE["disks"], _UNRAID_INI_CACHE["shares"])

    disks: dict[str, dict[str, str]] = {}
    shares: dict[str, dict[str, str]] = {}
    for d_path in ("/var/local/emhttp/disks.ini", "/host/var/local/emhttp/disks.ini"):
        if os.path.isfile(d_path):
            disks = _parse_ini_sections(d_path)
            if disks:
                break
    for s_path in ("/var/local/emhttp/shares.ini", "/host/var/local/emhttp/shares.ini"):
        if os.path.isfile(s_path):
            shares = _parse_ini_sections(s_path)
            if shares:
                break

    _UNRAID_INI_CACHE["ts"] = now
    _UNRAID_INI_CACHE["disks"] = disks
    _UNRAID_INI_CACHE["shares"] = shares
    return (disks, shares)


UNKNOWN_BACKING_DEV = "?unknown"  # a local disk we couldn't identify: treated as asleep (AI-08)


def resolve_path_backing_dev(path: str) -> str:
    """
    Resolves a filesystem path to its backing physical block device name (e.g. 'sda', 'sdb', 'nvme0n1')
    without touching the disk platter. Understands Unraid /mnt/user (shfs) share-to-pool mappings and
    dereferences symlinks via os.path.realpath to prevent cache symlinks from bypassing standby guards.
    """
    if not path:
        return ""
    try:
        path = os.path.realpath(path)
    except Exception:
        ignored("backend.services.rag_engine.resolve_path_backing_dev")
    norm = os.path.normpath(path).replace("\\", "/")
    if norm.startswith(("/app/data", "/mnt/cache", "/mnt/nvme", "/mnt/ssd", "/tmp")):
        return "nvme0n1"

    m = re.match(r"^/mnt/disk(\d+)(?:/|$)", norm)
    if m:
        disk_idx = int(m.group(1))
        fallback_dev = f"sd{chr(ord('a') + disk_idx)}" if 1 <= disk_idx <= 24 else ""
        # Respect explicit test/runtime Z_STATE entry if present
        if fallback_dev and fallback_dev in Z_STATE.cached_smart_data:
            return fallback_dev
        unraid_disks, _ = _get_unraid_disks_and_shares()
        d_info = unraid_disks.get(f"disk{disk_idx}")
        if d_info and d_info.get("device"):
            return d_info["device"]
        return fallback_dev

    m_share = re.match(r"^/mnt/(?:user|storage)(?:/([^/]+))?(?:/|$)", norm)
    if m_share:
        share_name = (m_share.group(1) or "").strip()
        unraid_disks, unraid_shares = _get_unraid_disks_and_shares()
        if share_name and share_name in unraid_shares:
            s_info = unraid_shares[share_name]
            use_cache = (s_info.get("useCache") or "").lower()
            cache_pool = s_info.get("cachePool") or ""
            if use_cache == "only":
                if cache_pool and cache_pool in unraid_disks and unraid_disks[cache_pool].get("device"):
                    return unraid_disks[cache_pool]["device"]
                return "nvme0n1"

        # Share uses HDD array (or is /mnt/user root): check if any array data disk is in standby
        array_devs: list[str] = []
        for _, d_info in unraid_disks.items():
            dev = d_info.get("device") or ""
            d_type = (d_info.get("type") or "").lower()
            d_status = (d_info.get("status") or "").upper()
            if dev and d_type == "data" and "NP" not in d_status:
                array_devs.append(dev)
                if (
                    str(d_info.get("spundown", "")).lower() in ("1", "true", "yes")
                    or "blink" in str(d_info.get("color") or "").lower()
                ):
                    return dev

        for dev in array_devs:
            cached = Z_STATE.cached_smart_data.get(dev)
            if cached and len(cached) >= 2 and str(cached[1] or "").lower() in ("standby", "sleep", "spundown"):
                return dev

        if array_devs:
            return array_devs[0]

    # Any other storage (ZFS, Btrfs, mdadm, LVM, plain disks): find the real disks (AI-08).
    # "sdb,sdc" means every one of them is checked; UNKNOWN_BACKING_DEV fails closed.
    try:
        from backend.hardware.blockdev import disks_for_path

        disks = disks_for_path(norm)
    except Exception:
        disks = None
    if disks is None:
        return UNKNOWN_BACKING_DEV
    return ",".join(disks)


def _disk_reports_standby(dev_name: str) -> bool:
    return is_backing_disk_in_standby(dev_name, check_smartctl=True)


def is_backing_disk_in_standby(dev_name: str, check_smartctl: bool = False) -> bool:
    """
    Non-waking check for whether a physical drive or filesystem path is in STANDBY/SLEEP mode.
    Strictly obeys AGENTS.md §1.2 (never wakes sleeping drives; uses -n standby if smartctl is invoked).
    """
    if not dev_name:
        return False
    if dev_name.startswith("/dev/"):
        dev_name = dev_name[5:]
    elif dev_name.startswith("/"):
        dev_name = resolve_path_backing_dev(dev_name)
    if dev_name == UNKNOWN_BACKING_DEV:
        # Couldn't tell which disk holds it: assume it may be asleep unless told otherwise (AI-08)
        return os.environ.get("ZETTNAS_STANDBY_UNKNOWN", "defer").strip().lower() != "allow"
    if "," in dev_name:
        return any(_disk_reports_standby(d) for d in dev_name.split(",") if d)
    if not dev_name or dev_name.startswith(("nvme", "loop", "ram", "zram")):
        return False

    cached = Z_STATE.cached_smart_data.get(dev_name)

    # 1. Check Unraid /var/local/emhttp/disks.ini if present (0ms, real-time kernel spin state, zero disk I/O)
    unraid_disks, _ = _get_unraid_disks_and_shares()
    for _, d_info in unraid_disks.items():
        if d_info.get("device") == dev_name:
            spundown_str = str(d_info.get("spundown", "")).lower()
            color_str = str(d_info.get("color") or "").lower()
            if spundown_str in ("1", "true", "yes") or "blink" in color_str:
                return True
            if spundown_str in ("0", "false", "no"):
                if cached and len(cached) >= 2 and str(cached[1] or "").lower() in ("standby", "sleep", "spundown"):
                    Z_STATE.smart.set_reading(dev_name, cached[0], "ok")
                return False

    # 2. Check in-memory Z_STATE.cached_smart_data (0ms)
    if cached and len(cached) >= 2:
        health = str(cached[1] or "").lower()
        if health in ("standby", "sleep", "spundown"):
            return True
        if health in ("ok", "warn", "crit", "passed", "active"):
            last_ts = Z_STATE.last_smart_scan.get(dev_name, 0.0)
            if (time.time() - last_ts) < 60.0:
                return False

    # 3. Live smartctl -n standby probe (cached 10s per device). Always used for disks we know
    #    nothing else about, e.g. on ZFS/Btrfs/mdadm systems (AI-08).
    if not check_smartctl and cached is None and not any(d.get("device") == dev_name for d in unraid_disks.values()):
        check_smartctl = True
    if check_smartctl:
        now = time.time()
        sc_cached = _SMARTCTL_STANDBY_CACHE.get(dev_name)
        if sc_cached and (now - sc_cached[0]) < 10.0:
            return sc_cached[1]

        dev_path = f"/host/dev/{dev_name}" if os.path.exists(f"/host/dev/{dev_name}") else f"/dev/{dev_name}"
        if os.path.exists(dev_path):
            try:
                r = subprocess.run(
                    ["smartctl", "-n", "standby", "-i", dev_path],
                    capture_output=True,
                    text=True,
                    timeout=4,
                )
                out_upper = ((r.stdout or "") + (r.stderr or "")).upper()
                open_failed = "OPEN DEVICE" in out_upper or "NO SUCH DEVICE" in out_upper
                is_low_power = (
                    "STANDBY" in out_upper
                    or "SLEEP" in out_upper
                    or (not open_failed and (r.returncode == 2 or (r.returncode & 2) != 0))
                )
                if is_low_power:
                    Z_STATE.smart.set_reading(dev_name, cached[0] if cached else None, "standby")
                    _SMARTCTL_STANDBY_CACHE[dev_name] = (now, True)
                    return True
                _SMARTCTL_STANDBY_CACHE[dev_name] = (now, False)
            except Exception:
                ignored("backend.services.rag_engine.is_backing_disk_in_standby")

    return False


def get_sleeping_disks_list() -> list[str]:
    """Returns list of device names currently known to be in standby/sleep state."""
    sleeping: set[str] = set()
    unraid_awake_devs: set[str] = set()
    unraid_disks, _ = _get_unraid_disks_and_shares()
    for _, d_info in unraid_disks.items():
        dev = d_info.get("device") or ""
        if not dev:
            continue
        spundown_str = str(d_info.get("spundown", "")).lower()
        color_str = str(d_info.get("color") or "").lower()
        if spundown_str in ("1", "true", "yes") or "blink" in color_str:
            sleeping.add(dev)
        elif spundown_str in ("0", "false", "no"):
            unraid_awake_devs.add(dev)
            cached = Z_STATE.cached_smart_data.get(dev)
            if cached and len(cached) >= 2 and str(cached[1] or "").lower() in ("standby", "sleep", "spundown"):
                Z_STATE.smart.set_reading(dev, cached[0], "ok")

    for dev, val in list(Z_STATE.smart.snapshot("cached_data").items()):
        if dev in unraid_awake_devs:
            continue
        if val and len(val) >= 2 and str(val[1] or "").lower() in ("standby", "sleep", "spundown"):
            sleeping.add(dev)
    return sorted(sleeping)


def get_running_disks_list() -> list[str]:
    """Returns list of device names currently known to be spinning/active."""
    sleeping = set(get_sleeping_disks_list())
    running: set[str] = set()
    for dev, val in list(Z_STATE.smart.snapshot("cached_data").items()):
        if dev and dev not in sleeping and val and len(val) >= 2:
            if str(val[1] or "").lower() not in ("standby", "sleep", "spundown"):
                running.add(dev)
    unraid_disks, _ = _get_unraid_disks_and_shares()
    for _, d_info in unraid_disks.items():
        dev = d_info.get("device") or ""
        status = (d_info.get("status") or "").upper()
        spundown_str = str(d_info.get("spundown", "")).lower()
        if dev and dev not in sleeping and "NP" not in status and spundown_str in ("0", "false", "no"):
            running.add(dev)
    return sorted(running)
