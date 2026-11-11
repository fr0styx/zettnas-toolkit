"""What needs attention, in plain words, for the Overview (UX-1). Every check reads data the
server already keeps (no disk is woken, nothing slow runs); one that fails is left out."""

from collections.abc import Callable
from typing import Any

from backend.config import logger

STORAGE_FULL_PCT = 90


def _safe(check: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]] | None:
    """The check's items, or None when it failed. A failed check used to count as "found nothing",
    at debug level, so the Overview said "Everything is fine" without having looked (SET-12)."""
    try:
        return check() or []
    except Exception:
        logger.warning("[StatusSummary] the check %s failed", getattr(check, "__name__", "?"), exc_info=True)
        return None


VERDICT_MAX_AGE = 7200  # the poller refreshes verdicts every 30 minutes


def _drives() -> list[dict[str, Any]]:
    import time

    from backend.state import Z_STATE

    out = []
    with Z_STATE.smart.lock:
        verdicts = {
            d: v
            for d, v in Z_STATE.smart.snapshot("verdicts").items()
            if time.time() - float(v.get("ts") or 0) < VERDICT_MAX_AGE
        }
    for dev, v in sorted(verdicts.items()):
        if v.get("verdict") not in ("now", "soon"):
            continue
        replace = v.get("kind") == "replace"
        out.append(
            {
                "id": f"drive:{dev}",
                "level": "critical" if v["verdict"] == "now" else "warning",
                "kind": ("drive_failing" if v["verdict"] == "now" else "drive_warning")
                if replace
                else "drive_attention",
                "subject": dev,
                "detail": v.get("summary", ""),
                # the interface shows the detail in the reader's language (dh.f.<key>.title)
                "detail_key": f"dh.f.{v['summary_key']}.title" if v.get("summary_key") else "",
                "detail_params": v.get("summary_params") or {},
                "open": "drives",
            }
        )
    for dev, (_, health) in sorted(Z_STATE.smart.snapshot("cached_data").items()):
        if dev in verdicts:
            continue
        if health in ("crit", "warn"):
            out.append(
                {
                    "id": f"drive:{dev}",
                    "level": "critical" if health == "crit" else "warning",
                    "kind": "drive_failing" if health == "crit" else "drive_warning",
                    "subject": dev,
                    "open": "drives",
                }
            )
    return out


def _pools() -> list[dict[str, Any]]:
    """Per pool (REL-11): degraded, a disk out, errors, scrub errors, 85 % / 95 % full."""
    from backend.services.pool_alerts import current

    return [{**i, "open": "drives" if i["kind"] in ("disk_disabled", "disk_errors") else "storage"} for i in current()]


def _storage() -> list[dict[str, Any]]:
    """The whole-server fill level, when the pools could not be read."""
    from backend.hardware.storage import read_storage
    from backend.services.pool_alerts import current

    if any(i["kind"] == "pool_full" for i in current()):
        return []

    st = read_storage() or {}
    pct = int(st.get("pct") or 0)
    if pct >= STORAGE_FULL_PCT:
        return [
            {
                "id": "storage:full",
                "level": "critical" if pct >= 97 else "warning",
                "kind": "storage_full",
                "subject": f"{pct}%",
                "open": "storage",
            }
        ]
    return []


def _backups() -> list[dict[str, Any]]:
    from backend.services.backup_watch import overdue_backups

    return [
        {
            "id": f"backup:{b.get('id')}",
            "level": "warning",
            "kind": "backup_overdue",
            "subject": b.get("name") or "",
            "open": "backup",
        }
        for b in overdue_backups()
    ]


def _protection() -> list[dict[str, Any]]:
    """Snapshot schedules and monthly checks that failed or are late (REL-12)."""
    from backend.services.protection_jobs import needing_attention

    return [
        {
            "id": f"{j['kind']}:{j['id']}",
            "level": "warning",
            "kind": "snapshot_overdue" if j["kind"] == "snapshot" else "scrub_overdue",
            "subject": j["name"],
            "open": "backup" if j["kind"] == "snapshot" else "storage",
        }
        for j in needing_attention()
    ]


def _kits() -> list[dict[str, Any]]:
    """Off-site backups whose recovery kit was never saved (REL-17)."""
    from backend.services.offsite_backup import kits_not_saved

    return [
        {"id": f"kit:{k['id']}", "level": "warning", "kind": "kit_not_saved", "subject": k["name"], "open": "backup"}
        for k in kits_not_saved()
    ]


def _stalled() -> list[dict[str, Any]]:
    """A background service that stopped going round its loop (REL-18)."""
    from backend.services.supervisor import stalled

    return [
        {"id": f"daemon:{n}", "level": "warning", "kind": "service_stalled", "subject": n, "open": "events"}
        for n in stalled()
    ]


def _frozen() -> list[dict[str, Any]]:
    from backend.services.ransomware_guard import writes_frozen

    if writes_frozen():
        return [{"id": "guard:frozen", "level": "critical", "kind": "writes_frozen", "subject": "", "open": "settings"}]
    return []


_PATH_CACHE: dict[str, Any] = {"at": -1e9, "ok": True}


def _nothing_switches_off() -> bool:
    """No way to switch the NAS off when the battery runs out; asked at most every five minutes,
    because it may look for the host's UPS service over the network."""
    import time as _time

    if _time.time() - _PATH_CACHE["at"] > 300:
        from backend.services.ups_watchdog import shutdown_path_report

        _PATH_CACHE.update(at=_time.time(), ok=bool(shutdown_path_report().get("ok")))
    return not _PATH_CACHE["ok"]


def _power() -> list[dict[str, Any]]:
    from backend.hardware.ups import read_ups_status
    from backend.services.ups_watchdog import ups_went_silent
    from backend.state import Z_STATE

    out = []
    from backend.hardware import ups_state

    ups = read_ups_status() or {}
    # every connection type: Overview knew one spelling ("OB") and missed a power cut on the others
    if ups_state.power_state(ups.get("status")) == ups_state.ON_BATTERY:
        out.append({"id": "ups:battery", "level": "warning", "kind": "on_battery", "subject": "", "open": "power"})
    # three more a household should see without opening Power (SET-15, Power 2)
    if ups_went_silent():
        out.append({"id": "ups:silent", "level": "critical", "kind": "ups_silent", "subject": "", "open": "power"})
    elif ups.get("unreadable") or ups.get("permission_error"):
        out.append(
            {"id": "ups:unreadable", "level": "warning", "kind": "ups_unreadable", "subject": "", "open": "power"}
        )
    if ups.get("available") and _nothing_switches_off():
        out.append({"id": "ups:nobody", "level": "critical", "kind": "power_nobody", "subject": "", "open": "power"})
    if getattr(Z_STATE, "critical_temp_active", False):
        # "too hot" opened the Event Log; the fans and the temperatures are on Hardware
        out.append({"id": "temp:critical", "level": "critical", "kind": "too_hot", "subject": "", "open": "hardware"})
    return out


def _password() -> list[dict[str, Any]]:
    from backend import config

    if config.is_using_default_password():
        return [
            {
                "id": "security:password",
                "level": "critical",
                "kind": "default_password",
                "subject": "",
                "open": "settings",
            }
        ]
    return []


def _security() -> list[dict[str, Any]]:
    """The security check's serious findings (critical or high), as one row: the Overview said
    "Everything is fine" while the security check showed red rows (SET-14). The first-time
    password has its own row above."""
    from backend.services.security_advisor import evaluate_security_posture

    issues = evaluate_security_posture(None).get("issues") or []
    serious = [
        i for i in issues if i.get("severity") in ("critical", "high") and i.get("id") != "sec-issue-default-password"
    ]
    if not serious:
        return []
    level = "critical" if any(i.get("severity") == "critical" for i in serious) else "warning"
    return [
        {
            "id": "security:check",
            "level": level,
            "kind": "security_look",
            "subject": str(len(serious)),
            "open": "settings",
        }
    ]


def _timezone() -> list[dict[str, Any]]:
    """No time zone chosen and none from the container: "night" (backups, scrubs, the AI's
    re-index) is night in UTC, which is the evening or the morning for most families."""
    from backend.services.identity import get_identity

    if get_identity().get("timezone"):
        return []
    return [{"id": "server:timezone", "level": "warning", "kind": "timezone_unset", "subject": "", "open": "time"}]


CHECKS = (
    _drives,
    _pools,
    _storage,
    _backups,
    _protection,
    _kits,
    _stalled,
    _frozen,
    _power,
    _password,
    _security,
    _timezone,
)


# What it takes to act on an item where its Open button leads (NUX-5)
ACT_SCOPES = {
    "drives": ("storage:admin", "storage:write"),
    "storage": ("storage:admin", "storage:write"),
    "backup": ("backup:manage", "backup:write"),
    "activity": ("system:config",),
    "events": ("system:config",),
    "hardware": ("hardware:fans", "system:config"),
    "settings": ("system:config",),
    "power": ("system:power", "system:config"),
    "time": ("system:config",),
}
# Things only the person who manages Kiboto can do anything about: nobody else is told
ADMIN_ONLY = {"default_password", "timezone_unset", "kit_not_saved", "service_stalled"}


def for_viewer(items: list[dict[str, Any]], can: Any) -> list[dict[str, Any]]:
    """The items as one person should see them: those they can't act on lose their Open button
    and say to tell the person who manages Kiboto; admin-only chores are left out (NUX-5)."""
    out = []
    for i in items:
        need = ACT_SCOPES.get(str(i.get("open") or ""), ())
        if not need or any(can(s) for s in need):
            out.append(i)
        elif i.get("kind") not in ADMIN_ONLY:
            out.append({**i, "open": None, "tell_admin": True})
    return out


def summary(can: Any = None) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    unchecked: list[str] = []
    for check in CHECKS:
        found = _safe(check)
        if found is None:
            unchecked.append(check.__name__.lstrip("_"))
        else:
            items.extend(found)
    if can is not None:
        items = for_viewer(items, can)
    items.sort(key=lambda i: 0 if i["level"] == "critical" else 1)
    # "ok" only when every check ran and found nothing: what was not checked is not fine
    return {"ok": not items and not unchecked, "items": items, "unchecked": unchecked}
