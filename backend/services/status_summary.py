"""What needs attention, in plain words, for the Overview (UX-1). Every check reads data the
server already keeps (no disk is woken, nothing slow runs); one that fails is left out."""

from collections.abc import Callable
from typing import Any

from backend.config import logger

STORAGE_FULL_PCT = 90


def _safe(check: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    try:
        return check() or []
    except Exception:
        logger.debug("[StatusSummary] check failed", exc_info=True)
        return []


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
        {"id": f"daemon:{n}", "level": "warning", "kind": "service_stalled", "subject": n, "open": "activity"}
        for n in stalled()
    ]


def _frozen() -> list[dict[str, Any]]:
    from backend.services.ransomware_guard import writes_frozen

    if writes_frozen():
        return [{"id": "guard:frozen", "level": "critical", "kind": "writes_frozen", "subject": "", "open": "settings"}]
    return []


def _power() -> list[dict[str, Any]]:
    from backend.hardware.ups import read_ups_status
    from backend.state import Z_STATE

    out = []
    status = str((read_ups_status() or {}).get("status") or "")
    if "OB" in status.split():
        out.append({"id": "ups:battery", "level": "warning", "kind": "on_battery", "subject": "", "open": "power"})
    if getattr(Z_STATE, "critical_temp_active", False):
        out.append({"id": "temp:critical", "level": "critical", "kind": "too_hot", "subject": "", "open": "activity"})
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


def _timezone() -> list[dict[str, Any]]:
    """No time zone chosen and none from the container: "night" (backups, scrubs, the AI's
    re-index) is night in UTC, which is the evening or the morning for most families."""
    from backend.services.identity import get_identity

    if get_identity().get("timezone"):
        return []
    return [{"id": "server:timezone", "level": "warning", "kind": "timezone_unset", "subject": "", "open": "time"}]


CHECKS = (_drives, _pools, _storage, _backups, _protection, _kits, _stalled, _frozen, _power, _password, _timezone)


def summary() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for check in CHECKS:
        items.extend(_safe(check))
    items.sort(key=lambda i: 0 if i["level"] == "critical" else 1)
    return {"ok": not items, "items": items}
