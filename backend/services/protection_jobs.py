"""Everything that protects the data, in one list (B12a, REL-12).

Backups (Hyper-Backup jobs and off-site repositories), snapshot schedules and pool scrubs are
"protection jobs": each one says when it last succeeded and whether it is fine, failed,
overdue, owned by the host, or unavailable. Failed and overdue ones are alerted once a day
(backup_watch) and listed on the Overview.

Scrubs run once a month on the hosts where ZettNAS owns the pools (ZettOS and plain Linux).
A scrub reads every disk, so it is on by default only for pools of SSDs; for a pool with
spinning disks a person switches it on and confirms that the disks will spin up once a month.
Unraid, TrueNAS and the other appliances run their own parity checks and scrubs: ZettNAS says
so and does not add a second one.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from backend import config
from backend.config import logger
from backend.fsutil import atomic_write_json, locked_json, read_json

SCRUB_EVERY_S = 30 * 86400
SCRUB_OVERDUE_S = 2 * 31 * 86400
SCRUB_HOUR = 3  # local time; the scheduler starts a due scrub in this hour
OWNED = ("zettos", "generic_linux")
HOST_NAMES = {
    "unraid": "Unraid",
    "truenas": "TrueNAS",
    "proxmox": "Proxmox",
    "ugos": "UGOS",
    "fygoos": "the NAS system",
}
EVERY = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}


def _scrub_file() -> str:
    return os.path.join(config.DATA_DIR, "scrub_schedules.json")


def _platform(adapter: Any) -> str:
    try:
        return str(adapter.get_platform_type().value)
    except Exception:
        return ""


def _ssd_only(pool: Any) -> bool:
    members = [m for m in (getattr(pool, "members", None) or []) if getattr(m, "role", "") != "boot"]
    return bool(members) and not any(getattr(m, "rotational", True) for m in members)


def scrub_settings() -> dict[str, dict[str, Any]]:
    data = read_json(_scrub_file(), {}) or {}
    return data if isinstance(data, dict) else {}


def scrub_enabled(pool: Any, settings: dict[str, dict[str, Any]] | None = None) -> bool:
    """A person's choice, else on for SSD-only pools and off where it would spin disks up."""
    saved = (settings if settings is not None else scrub_settings()).get(pool.id) or {}
    if isinstance(saved.get("enabled"), bool):
        return saved["enabled"]
    return _ssd_only(pool)


def set_scrub(pool_id: str, enabled: bool) -> dict[str, Any]:
    with locked_json(_scrub_file()):
        data = scrub_settings()
        entry = dict(data.get(pool_id) or {})
        entry.update(enabled=bool(enabled), changed_at=time.time())
        data[pool_id] = entry
        atomic_write_json(_scrub_file(), data)
    return entry


def needs_wake_confirmation(pool: Any) -> bool:
    """Switching a monthly scrub on spins this pool's disks up: the person confirms it."""
    return not _ssd_only(pool)


def _job(kind: str, jid: str, name: str, status: str, why: str = "", **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "id": jid, "name": name, "status": status, "why": why, **extra}


def _backups(now: float) -> list[dict[str, Any]]:
    from backend.services.backup_watch import overdue_backups

    late = {(b["kind"], b["id"]): b for b in overdue_backups(now)}
    out = []
    try:
        from backend.services.backup_engine import get_backup_jobs

        for j in get_backup_jobs():
            if not j.get("enabled", True):
                continue
            b = late.get(("hyper", j.get("id")))
            failed = b and "failed" in b["why"]
            out.append(
                _job(
                    "backup",
                    str(j.get("id")),
                    str(j.get("name") or ""),
                    "failed" if failed else ("overdue" if b else "ok"),
                    b["why"] if b else "",
                    schedule=j.get("schedule") or "",
                    last_ok=j.get("last_success_at") or None,
                )
            )
    except Exception:
        logger.debug("[Protection] backup jobs unreadable", exc_info=True)
    try:
        from backend.services.offsite_backup import list_repos

        for r in list_repos():
            if r.get("hour") is None:
                continue
            b = late.get(("offsite", r.get("id")))
            failed = b and "failed" in b["why"]
            out.append(
                _job(
                    "offsite",
                    str(r.get("id")),
                    str(r.get("name") or ""),
                    "failed" if failed else ("overdue" if b else "ok"),
                    b["why"] if b else "",
                    schedule="daily",
                    last_ok=r.get("last_backup") or None,
                )
            )
    except Exception:
        logger.debug("[Protection] off-site repositories unreadable", exc_info=True)
    return out


def _snapshots(now: float) -> list[dict[str, Any]]:
    from backend.services import snapshot_service

    ok, why_not = snapshot_service.availability()
    out = []
    for s in snapshot_service.list_schedules():
        share = str(s.get("share") or "")
        every = EVERY.get(str(s.get("every") or "daily"), 86400)
        last = float(s.get("last_run") or 0)
        result = str(s.get("last_result") or "")
        if not ok:
            status, why = "unavailable", why_not
        elif result.startswith("failed"):
            status, why = "failed", result
        elif now - max(last, float(s.get("created_at") or now)) > 2 * every:
            status, why = "overdue", "no snapshot was taken lately"
        else:
            status, why = "ok", ""
        out.append(
            _job("snapshot", share, share, status, why, schedule=s.get("every") or "daily", last_ok=last or None)
        )
    return out


def _scrubs(now: float) -> list[dict[str, Any]]:
    from backend.hardware.pal_storage import get_storage_platform

    adapter = get_storage_platform()
    platform = _platform(adapter)
    caps = adapter.get_capabilities()
    settings = scrub_settings()
    out = []
    for p in adapter.list_pools():
        if p.pool_type in ("single", "jbod") and p.fs_type not in ("zfs", "btrfs"):
            continue
        if p.fs_type not in ("zfs", "btrfs") and p.pool_type != "unraid_array":
            continue
        try:
            last = adapter.scrub_result(p) or {}
        except Exception:
            last = {}
        finished = last.get("finished_at")
        common = {"schedule": "monthly", "last_ok": finished, "errors": int(last.get("errors") or 0)}
        if platform not in OWNED:
            host = HOST_NAMES.get(platform, "the host")
            out.append(_job("scrub", p.id, p.name, "host_owned", f"{host} runs its own checks of this pool", **common))
            continue
        if not getattr(caps, "can_trigger_scrub", False):
            out.append(_job("scrub", p.id, p.name, "unavailable", "the scrub tools are missing", **common))
            continue
        enabled = scrub_enabled(p, settings)
        if not enabled:
            why = "off: a scrub spins up the pool's disks once a month" if not _ssd_only(p) else "off"
            out.append(_job("scrub", p.id, p.name, "off", why, enabled=False, **common))
            continue
        started = float((settings.get(p.id) or {}).get("changed_at") or now)
        reference = float(finished) if finished else started
        status = "overdue" if now - reference > SCRUB_OVERDUE_S else "ok"
        why = "the pool has not been checked for errors lately" if status == "overdue" else ""
        out.append(_job("scrub", p.id, p.name, status, why, enabled=True, **common))
    return out


def jobs(now: float | None = None) -> list[dict[str, Any]]:
    now = now or time.time()
    out: list[dict[str, Any]] = []
    for part in (_backups, _snapshots, _scrubs):
        try:
            out.extend(part(now))
        except Exception:
            logger.debug("[Protection] %s unreadable", part.__name__, exc_info=True)
    return out


def needing_attention(now: float | None = None) -> list[dict[str, Any]]:
    """Snapshot schedules and scrubs that failed or are overdue (backups have their own check)."""
    return [j for j in jobs(now) if j["kind"] in ("snapshot", "scrub") and j["status"] in ("failed", "overdue")]


_LAST_ALERT = {"at": 0.0}
ALERT_EVERY_S = 3600


def check_and_alert(now: float | None = None, send=None) -> list[dict[str, Any]]:
    """Once an hour from the scheduler: one alert a day for each late or failed snapshot schedule
    and monthly check (backups have theirs in backup_watch)."""
    now = now or time.time()
    if send is None and now - _LAST_ALERT["at"] < ALERT_EVERY_S:
        return []
    _LAST_ALERT["at"] = now
    found = needing_attention(now)
    if not found:
        return []
    if send is None:
        from backend.services.notifications import send_notification as send
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    for j in found:
        what = "Snapshots of" if j["kind"] == "snapshot" else "The monthly check of"
        try:
            send(
                f"{what} {j['name']} need attention",
                f"{what} {j['name']}: {j['why']}. Open Backup to see why.",
                level="warning",
                event_type="backup",
                dedup_key=f"protection-{j['kind']}-{j['id']}-{day}",
            )
        except Exception:
            logger.warning("[Protection] alert failed", exc_info=True)
    return found


def run_scrubs_due(now: float | None = None) -> list[str]:
    """From the scheduler every minute: in the scrub hour, start the scrubs that are due."""
    from backend.hardware.pal_storage import get_storage_platform

    now = now or time.time()
    if time.localtime(now).tm_hour != SCRUB_HOUR:
        return []
    adapter = get_storage_platform()
    if _platform(adapter) not in OWNED or not getattr(adapter.get_capabilities(), "can_trigger_scrub", False):
        return []
    try:
        if adapter.is_storage_busy():
            return []
    except Exception:
        return []
    started = []
    with locked_json(_scrub_file()):
        settings = scrub_settings()
        for p in adapter.list_pools():
            if p.fs_type not in ("zfs", "btrfs") or not scrub_enabled(p, settings):
                continue
            entry = dict(settings.get(p.id) or {})
            last = adapter.scrub_result(p) or {}
            done = float(last.get("finished_at") or 0)
            if now - max(done, float(entry.get("last_started") or 0)) < SCRUB_EVERY_S or last.get("state") == "running":
                continue
            res = adapter.trigger_scrub(f"zfs:{p.id}" if p.fs_type == "zfs" else p.id, "start")
            entry["last_started"] = now
            entry["last_start_result"] = str(res.get("status") or "")
            settings[p.id] = entry
            started.append(p.id)
            logger.info(f"[Protection] Monthly scrub of {p.name}: {entry['last_start_result']}")
        if started:
            atomic_write_json(_scrub_file(), settings)
    return started


WATCH_TICK_S = 60


def watch_daemon(stop: threading.Event | None = None, tick: float = WATCH_TICK_S) -> None:
    """Its own supervised thread, BackupWatch (REL-18): a backup or scheduled job that hangs the
    task scheduler can no longer silence the "your backup hasn't run" alerts."""
    from backend.services import backup_watch
    from backend.services.supervisor import beat

    stop = stop or threading.Event()
    while not stop.is_set():
        beat("BackupWatch")
        now = time.time()
        try:
            backup_watch.check_and_alert(now)
        except Exception:
            logger.warning("[Protection] backup check failed", exc_info=True)
        try:
            check_and_alert(now)  # snapshots and monthly checks (REL-12)
        except Exception:
            logger.warning("[Protection] protection check failed", exc_info=True)
        try:
            alert_stalled(now)  # a stuck scheduler stops snapshots and backups at once (NREL-18)
        except (OSError, RuntimeError, ValueError):
            logger.warning("[Protection] stalled-service check failed", exc_info=True)
        if stop.wait(tick):
            break


def alert_stalled(now: float | None = None, send=None) -> list[str]:
    """One alert a day for each background service that stopped answering; the Overview alone
    reaches nobody who doesn't open it (NREL-18)."""
    from backend.services.supervisor import label, stalled

    names = stalled()
    if not names:
        return []
    if send is None:
        from backend.services.notifications import send_notification as send
    day = time.strftime("%Y-%m-%d", time.gmtime(now or time.time()))
    for name in names:
        send(
            f"ZettNAS: the {label(name)} service stopped responding",
            f"The {label(name)} service hasn't checked in for a while, so the work it does "
            "(snapshots, checks, backups) may not be running. Restart ZettNAS if it doesn't recover.",
            level="warning",
            event_type="system",
            dedup_key=f"stalled-{name}-{day}",
        )
    return names
