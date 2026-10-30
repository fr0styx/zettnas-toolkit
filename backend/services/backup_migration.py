"""Moving a copy job to an off-site (restic) backup (REL-9, decision 8).

A module of its own: it needs both backup engines, and neither may import the other.
"""

import os
import re
from typing import Any

from backend.services import backup_engine as be
from backend.services import offsite_backup


def migrate_to_offsite(job_id: str) -> dict[str, Any]:
    """Moves a copy job to an off-site (restic) backup of the same folder on the same remote, in a
    folder of its own next to the old copy, which stays untouched (REL-9, decision 8). The copy
    job keeps running until the new backup's first run succeeds (NREL-19), so a failed first
    backup never leaves the folder with no working off-site copy."""
    job = next((j for j in be.get_backup_jobs() if j.get("id") == job_id), None)
    if not job:
        raise KeyError("No such backup job.")
    remote = str(job.get("remote_name") or "").strip()
    if job.get("kind") == "config" or job.get("destination_type") != "remote" or not remote:
        raise ValueError("Only a copy of a folder to a cloud remote can be moved to an off-site backup.")
    subvol = be.checked_subvolume(job.get("source_subvolume", ""))
    pool_path = be.get_storage_platform().get_pool_path(job.get("source_pool", "default"))
    source = os.path.join(pool_path, "@shares", subvol) if subvol else pool_path
    if subvol and not os.path.isdir(source):
        source = os.path.join(pool_path, subvol)
    remote_path = str(job.get("remote_path") or "").strip().strip("/")
    location = f"rclone:{remote}:{remote_path + '-restic' if remote_path else 'zettnas-restic'}"
    repo_id = re.sub(r"[^a-z0-9-]+", "-", f"from-{job_id}".lower()).strip("-")[:41]
    hour = None if job.get("schedule") == "manual" else 2
    retention = max(1, int(job.get("retention_count") or 7))
    keep = {"daily": max(7, retention), "weekly": 4, "monthly": 12}
    repo = offsite_backup.save_repo(repo_id, str(job.get("name") or repo_id), location, [source], keep, hour)
    offsite_backup.init(repo_id)
    offsite_backup._update(repo_id, replaces_job=job_id)
    be._update_job_status(job_id, migrated_to=repo_id)
    be.logger.info(f"[HYPER-BACKUP] Copy job {job_id} moves to the off-site backup {repo_id} at {location}")
    return {
        "status": "migrated",
        "job_id": job_id,
        "repo": offsite_backup.get_repo(repo_id) | {"same_disk": repo.get("same_disk", False)},
    }


def retire_replaced_jobs() -> list[str]:
    """Turns off each copy job whose off-site backup has now succeeded once (NREL-19). Called by
    the scheduler; returns the jobs turned off."""
    retired = []
    for repo in offsite_backup.list_repos():
        job_id = str(repo.get("replaces_job") or "")
        if not job_id or repo.get("last_result") != "ok" or not repo.get("last_backup"):
            continue
        be._update_job_status(job_id, enabled=False)
        offsite_backup._update(repo["id"], replaces_job="")
        be.logger.info(
            "[HYPER-BACKUP] Copy job %s is off: the off-site backup %s has its first version", job_id, repo["id"]
        )
        retired.append(job_id)
    return retired
