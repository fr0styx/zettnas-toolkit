"""Pool health that reaches a person (B12a, REL-11 / FEAT-05).

A degraded pool, a disabled or missing disk, disk errors, scrub (or parity check) errors and a
pool that is 85 % or 95 % full become alerts, show on the Overview, and go into a weekly health
report. Everything is read from what the host already keeps (Unraid's ini files, zpool status,
btrfs's saved scrub status): no disk is woken.

An alert goes out when a problem appears, a critical one is repeated once a day while it lasts,
and a short note says when it is fixed.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

from backend import config
from backend.config import logger
from backend.fsutil import atomic_write_json, locked_json, read_json

FULL_WARN_PCT = 85
FULL_CRIT_PCT = 95
CHECK_EVERY_S = 300
REMIND_CRITICAL_S = 86400
CACHE_S = 300
WEEKLY_DAY = 6  # Sunday (time.struct_time.tm_wday)
WEEKLY_HOUR = 9

GOOD_POOL = {"HEALTHY", "ONLINE", "STANDBY", "SYNCING", "OK"}
BAD_MEMBER = {
    "DISABLED",
    "DISK_DSBL",
    "DISK_DSBL_NEW",
    "DISK_INVALID",
    "DISK_NP_DSBL",
    "DISK_NP_MISSING",
    "DISK_WRONG",
    "MISSING",
    "FAULTED",
    "UNAVAIL",
    "REMOVED",
    "OFFLINE",
    "DEGRADED",
}

_cache: dict[str, Any] = {"at": 0.0, "items": []}
_cache_lock = threading.Lock()
_last_check = {"at": 0.0}


def _state_file() -> str:
    return os.path.join(config.DATA_DIR, "pool_alerts.json")


from backend.hardware.pal.scrub_parse import parse_btrfs_scrub, parse_zpool_scan  # noqa: E402,F401


# --- what is wrong -----------------------------------------------------------------------------
def problems(pools: list[Any], scrubs: dict[str, dict[str, Any] | None] | None = None) -> list[dict[str, Any]]:
    """[{id, level, kind, subject, pool, detail}] for the pools and their last scrubs."""
    scrubs = scrubs or {}
    out: list[dict[str, Any]] = []
    for p in pools:
        name = getattr(p, "name", "") or getattr(p, "id", "")
        pid = getattr(p, "id", name)
        status = str(getattr(p, "status", "HEALTHY") or "HEALTHY").upper()
        if status not in GOOD_POOL:
            out.append(
                {
                    "id": f"pool:{pid}:degraded",
                    "level": "critical",
                    "kind": "pool_degraded",
                    "subject": name,
                    "detail": status,
                }
            )
        for m in getattr(p, "members", None) or []:
            mstatus = str(getattr(m, "status", "OK") or "OK").upper()
            disk = getattr(m, "name", "") or getattr(m, "device", "")
            if mstatus in BAD_MEMBER:
                out.append(
                    {
                        "id": f"pool:{pid}:disk:{disk}",
                        "level": "critical",
                        "kind": "disk_disabled",
                        "subject": f"{disk} ({name})",
                        "detail": mstatus,
                    }
                )
            elif int(getattr(m, "num_errors", 0) or 0) > 0:
                out.append(
                    {
                        "id": f"pool:{pid}:errors:{disk}",
                        "level": "warning",
                        "kind": "disk_errors",
                        "subject": f"{disk} ({name})",
                        "detail": str(int(m.num_errors)),
                    }
                )
        pct = float(getattr(p, "used_pct", 0) or 0)
        if pct >= FULL_WARN_PCT and int(getattr(p, "total_bytes", 0) or 0) > 0:
            out.append(
                {
                    "id": f"pool:{pid}:full",
                    "level": "critical" if pct >= FULL_CRIT_PCT else "warning",
                    "kind": "pool_full",
                    "subject": name,
                    "detail": f"{round(pct)}%",
                }
            )
        scrub = scrubs.get(pid)
        if scrub and int(scrub.get("errors") or 0) > 0:
            out.append(
                {
                    "id": f"pool:{pid}:scrub",
                    "level": "critical",
                    "kind": "scrub_errors",
                    "subject": name,
                    "detail": str(int(scrub["errors"])),
                }
            )
    out.sort(key=lambda i: 0 if i["level"] == "critical" else 1)
    return out


def _read() -> tuple[list[Any], dict[str, dict[str, Any] | None]]:
    from backend.hardware.pal_storage import get_storage_platform

    adapter = get_storage_platform()
    pools = list(adapter.list_pools())
    scrubs: dict[str, dict[str, Any] | None] = {}
    for p in pools:
        try:
            scrubs[p.id] = adapter.scrub_result(p)
        except Exception:
            logger.debug("[PoolAlerts] no scrub result for %s", p.id, exc_info=True)
            scrubs[p.id] = None
    return pools, scrubs


def current(max_age: float = CACHE_S, now: float | None = None) -> list[dict[str, Any]]:
    """The problems now, read at most every max_age seconds (the Overview asks often)."""
    now = now or time.time()
    with _cache_lock:
        if now - _cache["at"] < max_age:
            return list(_cache["items"])
    try:
        pools, scrubs = _read()
        items = problems(pools, scrubs)
    except Exception:
        logger.debug("[PoolAlerts] could not read the pools", exc_info=True)
        items = []
    with _cache_lock:
        _cache.update(at=now, items=items)
    return list(items)


# --- alerts ------------------------------------------------------------------------------------
TITLES = {
    "pool_degraded": "Storage pool {subject} is degraded",
    "disk_disabled": "Disk {subject} is {detail}",
    "disk_errors": "Disk {subject} reports {detail} errors",
    "pool_full": "Storage pool {subject} is {detail} full",
    "scrub_errors": "The last check of {subject} found {detail} errors",
}
ADVICE = {
    "pool_degraded": "Your data has less protection until it is fixed. Open Storage and check the disks.",
    "disk_disabled": "Replace or reconnect it soon; until then a second failure can lose data.",
    "disk_errors": "Keep an eye on it in Drive Health; replace it if the errors keep growing.",
    "pool_full": "Delete or move files, or add a disk, before it fills up completely.",
    "scrub_errors": "Some data could not be read back correctly. Check Drive Health and your backups.",
}


def _text(item: dict[str, Any]) -> tuple[str, str]:
    title = (TITLES.get(item["kind"]) or str(item["kind"])).format(**item)
    return title, f"{title}. {ADVICE.get(item['kind'], '')}".strip()


def check_and_alert(now: float | None = None, send=None) -> dict[str, list[str]]:
    """Every CHECK_EVERY_S from the scheduler: new problems alert, critical ones are repeated
    daily, fixed ones get a short note. Returns what was sent, by kind of message."""
    now = now or time.time()
    if send is None and now - _last_check["at"] < CHECK_EVERY_S:
        return {"new": [], "reminded": [], "fixed": []}
    _last_check["at"] = now
    if send is None:
        from backend.services.notifications import send_notification as send
    items = {i["id"]: i for i in current(max_age=0, now=now)}
    sent: dict[str, list[str]] = {"new": [], "reminded": [], "fixed": []}
    with locked_json(_state_file()):
        state = read_json(_state_file(), {}) or {}
        for pid, item in items.items():
            prev = state.get(pid)
            title, message = _text(item)
            if prev is None or (item["level"] == "critical" and prev.get("level") != "critical"):
                send(
                    title=f"ZettNAS: {title}", message=message, level=item["level"], event_type="storage", dedup_key=pid
                )
                state[pid] = {"first": now, "last_sent": now, "level": item["level"], "title": title}
                sent["new"].append(pid)
            elif item["level"] == "critical" and now - float(prev.get("last_sent") or 0) >= REMIND_CRITICAL_S:
                send(
                    title=f"ZettNAS: still — {title}",
                    message=message,
                    level="critical",
                    event_type="storage",
                    dedup_key=f"{pid}:reminder",
                )
                prev.update(last_sent=now, level=item["level"])
                sent["reminded"].append(pid)
            else:
                prev["level"] = item["level"]
        for pid in [p for p in state if p not in items and p.startswith("pool:")]:
            gone = state.pop(pid)
            send(
                title=f"ZettNAS: fixed — {gone.get('title') or pid}",
                message="This storage problem is gone.",
                level="info",
                event_type="storage",
                dedup_key=f"{pid}:fixed",
            )
            sent["fixed"].append(pid)
        atomic_write_json(_state_file(), state)
    return sent


# --- the weekly report -------------------------------------------------------------------------
def weekly_report(now: float | None = None) -> tuple[str, str]:
    """A short summary of how the server is doing: pools, drives and backups."""
    from backend.hardware.pal_storage import get_storage_platform
    from backend.state import Z_STATE

    now = now or time.time()
    lines: list[str] = []
    try:
        adapter = get_storage_platform()
        for p in adapter.list_pools():
            if not p.total_bytes:
                continue
            try:
                scrub = adapter.scrub_result(p)
            except Exception:
                scrub = None
            check = ""
            if scrub and scrub.get("finished_at"):
                days = int((now - float(scrub["finished_at"])) // 86400)
                check = f", last checked {days} day(s) ago with {int(scrub.get('errors') or 0)} errors"
            lines.append(f"- {p.name}: {round(p.used_pct)}% used, {str(p.status).lower()}{check}")
    except Exception:
        logger.debug("[PoolAlerts] weekly report: pools unavailable", exc_info=True)
    with Z_STATE.smart.lock:
        verdicts = dict(Z_STATE.drive_verdicts)
    attention = [d for d, v in verdicts.items() if v.get("verdict") in ("now", "soon")]
    if verdicts:
        lines.append(
            f"- Drives: {len(verdicts) - len(attention)} of {len(verdicts)} fine"
            + (f"; needs attention: {', '.join(sorted(attention))}" if attention else "")
        )
    try:
        from backend.services.backup_watch import overdue_backups

        late = [b.get("name") or "" for b in overdue_backups(now)]
        lines.append(f"- Backups: {'overdue: ' + ', '.join(late) if late else 'all on time'}")
    except Exception:
        logger.debug("[PoolAlerts] weekly report: backups unavailable", exc_info=True)
    issues = current(max_age=CACHE_S, now=now)
    head = (
        "Everything looks fine."
        if not issues and not attention
        else f"{len(issues) + len(attention)} thing(s) need attention."
    )
    for i in issues:
        lines.append(f"! {_text(i)[0]}")
    return "ZettNAS weekly health report", head + "\n\n" + "\n".join(lines)


def send_weekly_if_due(now: float | None = None, send=None) -> bool:
    """From the scheduler every minute: on Sunday at 9 (local time), once a week."""
    from backend.services.notifications import load_notification_config

    now = now or time.time()
    cfg = load_notification_config()
    if not cfg.get("weekly_report", True):
        return False
    t = time.localtime(now)
    if t.tm_wday != int(cfg.get("weekly_day", WEEKLY_DAY)) or t.tm_hour != int(cfg.get("weekly_hour", WEEKLY_HOUR)):
        return False
    with locked_json(_state_file()):
        state = read_json(_state_file(), {}) or {}
        if now - float(state.get("_weekly_at") or 0) < 6 * 86400:
            return False
        state["_weekly_at"] = now
        atomic_write_json(_state_file(), state)
    if send is None:
        from backend.services.notifications import send_notification as send
    title, message = weekly_report(now)
    send(title=title, message=message, level="normal", event_type="health", dedup_key="weekly_health")
    return True
