"""
"Your backup hasn't run" alerts (audit batch 1, REL-1 follow-up).

A backup that silently stopped is the worst kind: everything looks fine until the
day it's needed. Once an hour this looks at every scheduled backup (Hyper-Backup
jobs and offsite restic repositories) and sends one alert a day for each that has
no successful run within twice its interval, or whose last run failed.
"""

import logging
import time
from typing import Any

logger = logging.getLogger("ZettNAS")

CHECK_EVERY_SECS = 3600
_LAST_CHECK = {"at": 0.0}
INTERVALS = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}


def overdue_backups(now: float | None = None) -> list[dict[str, Any]]:
    """Scheduled backups without a recent success: [{"id", "name", "kind", "why"}]."""
    now = now or time.time()
    out: list[dict[str, Any]] = []
    try:
        from backend.services.backup_engine import get_backup_jobs

        for job in get_backup_jobs():
            interval = INTERVALS.get(str(job.get("schedule") or ""))
            if not interval or not job.get("enabled", True):
                continue
            created = float(job["created_at"]) if job.get("created_at") is not None else now
            last_ok = float(
                job.get("last_success_at")
                or (job.get("last_run_at") if job.get("last_status") == "success" else 0)
                or 0
            )
            if job.get("last_status") in ("error", "interrupted"):
                why = "its last run failed" if job.get("last_status") == "error" else "its last run was interrupted"
                out.append({"id": job.get("id"), "name": job.get("name"), "kind": "hyper", "why": why})
            elif now - max(last_ok, created) > 2 * interval:
                out.append(
                    {"id": job.get("id"), "name": job.get("name"), "kind": "hyper", "why": "it hasn't run lately"}
                )
    except Exception:
        logger.debug("backup_watch: Hyper-Backup jobs unreadable", exc_info=True)
    try:
        from backend.services.offsite_backup import list_repos

        for repo in list_repos():
            if repo.get("hour") is None:
                continue
            created = float(repo["created_at"]) if repo.get("created_at") is not None else now
            result = str(repo.get("last_result") or "")
            if result.startswith("failed") or result.startswith("check failed"):
                out.append(
                    {"id": repo.get("id"), "name": repo.get("name"), "kind": "offsite", "why": "its last run failed"}
                )
            elif now - max(float(repo.get("last_backup") or 0), created) > 2 * 86400:
                out.append(
                    {"id": repo.get("id"), "name": repo.get("name"), "kind": "offsite", "why": "it hasn't run lately"}
                )
    except Exception:
        logger.debug("backup_watch: offsite repositories unreadable", exc_info=True)
    return out


def check_and_alert(now: float | None = None) -> list[dict[str, Any]]:
    """Called every minute by the scheduler; looks once an hour and alerts once a day per backup."""
    now = now or time.time()
    if now - _LAST_CHECK["at"] < CHECK_EVERY_SECS:
        return []
    _LAST_CHECK["at"] = now
    found = overdue_backups(now)
    if not found:
        return []
    from backend.services.notifications import send_notification

    day = time.strftime("%Y-%m-%d", time.localtime(now))
    for b in found:
        try:
            send_notification(
                f"Backup needs attention: {b['name']}",
                f'The backup "{b["name"]}" has no recent successful run: {b["why"]}. Open Backup to see why.',
                level="warning",
                event_type="backup",
                dedup_key=f"backup-overdue-{b['kind']}-{b['id']}-{day}",
            )
        except Exception:
            logger.warning("backup_watch: alert failed", exc_info=True)
    return found
