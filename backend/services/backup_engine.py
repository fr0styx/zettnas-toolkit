"""
ZettNAS Toolkit - Backup Engine Service
Handles generation and safe restoration of configuration archives,
plus Hyper-Backup 3-2-1 automated pipelines (snapshots + Rclone offsite sync)
and background scheduling.
"""

import io
import os
import threading
import time
import uuid
import zipfile
from typing import Any, BinaryIO, Dict, List, Optional

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.pal_storage import PlatformCapabilityError, get_storage_platform
from backend.services.rclone_engine import get_rclone_engine

# Files to exclude from configuration backups
BACKUP_EXCLUSIONS = {
    "history.db",
    "history.db-shm",
    "history.db-wal",
    "sessions.json",
    "api_tokens.json",
}

MAX_RESTORE_BYTES = 50 * 1024 * 1024  # 50MB max cumulative restore size
MAX_MEMBER_COUNT = 1000

BACKUP_JOBS_FILE = os.path.join(DATA_DIR, "backup_jobs.json")
BACKUP_HISTORY_FILE = os.path.join(DATA_DIR, "backup_history.json")


def generate_backup_zip_stream() -> io.BytesIO:
    """Generates an in-memory zip archive of configuration files in DATA_DIR.

    Excludes volatile database histories, session tokens, and API tokens.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(DATA_DIR):
            dirs[:] = [d for d in dirs if d not in {"__pycache__", ".pytest_cache", ".git"}]
            for file in files:
                if (
                    file in BACKUP_EXCLUSIONS
                    or file.endswith((".pyc", ".tmp", ".swp"))
                    or file.startswith((".tmp-", ".DS_Store"))
                ):
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, DATA_DIR)
                z.write(file_path, rel_path)
    buf.seek(0)
    return buf


def restore_backup_archive(archive_file: BinaryIO) -> None:
    """Safely extracts a backup zip archive into DATA_DIR.

    Performs zip-slip validation, symlink rejection, and size limitation
    to ensure no malicious payloads escape DATA_DIR or exhaust disk storage.
    """
    target_dir = os.path.abspath(DATA_DIR)
    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(archive_file, "r") as z:
        members = z.infolist()
        if len(members) > MAX_MEMBER_COUNT:
            raise ValueError(f"Backup archive exceeds maximum allowable file count ({MAX_MEMBER_COUNT})")

        total_size = 0
        for member in members:
            # Check for symlink attribute (Unix mode 0o120000)
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Symlinks are forbidden in backup archive: {member.filename}")

            total_size += member.file_size
            if total_size > MAX_RESTORE_BYTES:
                raise ValueError("Backup archive exceeds maximum allowable uncompressed size (50MB)")

            # Validate target path against directory traversal
            extracted_path = os.path.abspath(os.path.join(target_dir, member.filename))
            if not extracted_path.startswith(target_dir + os.sep) and extracted_path != target_dir:
                raise ValueError(f"Illegal path in archive: {member.filename}")

        # Safe extraction: use Python 3.12+ data filter if available
        try:
            z.extractall(target_dir, filter="data")
        except TypeError:
            # Fallback for Python versions prior to 3.12
            for member in members:
                if not member.is_dir():
                    z.extract(member, target_dir)

    logger.info("[BACKUP] Configuration restored successfully from backup archive.")


# =========================================================================
# Hyper-Backup Orchestrator: Jobs, Snapshots & 3-2-1 Cloud Sync
# =========================================================================

def get_backup_jobs() -> List[Dict[str, Any]]:
    """Retrieves all scheduled hyper-backup jobs."""
    raw = read_json(BACKUP_JOBS_FILE, default=[])
    if isinstance(raw, list):
        return raw
    return []


def save_backup_job(job_data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates or updates a scheduled hyper-backup job."""
    jobs = get_backup_jobs()
    job_id = job_data.get("id") or str(uuid.uuid4())[:8]
    now = time.time()

    normalized: Dict[str, Any] = {
        "id": job_id,
        "name": job_data.get("name", "Untitled Backup Task").strip() or "Untitled Backup Task",
        "source_pool": job_data.get("source_pool", "default"),
        "source_subvolume": job_data.get("source_subvolume", "").strip(),
        "destination_type": job_data.get("destination_type", "remote"),  # "remote" or "local_snapshot"
        "remote_name": job_data.get("remote_name", "").strip(),
        "remote_path": job_data.get("remote_path", "").strip(),
        "schedule": job_data.get("schedule", "daily"),  # "hourly", "daily", "weekly", "manual"
        "retention_count": max(1, int(job_data.get("retention_count", 7))),
        "enabled": bool(job_data.get("enabled", True)),
        "last_run_at": job_data.get("last_run_at"),
        "last_status": job_data.get("last_status", "idle"),
        "last_error": job_data.get("last_error"),
        "created_at": job_data.get("created_at", now),
        "updated_at": now,
    }

    # Find existing index
    idx = next((i for i, j in enumerate(jobs) if j.get("id") == job_id), None)
    if idx is not None:
        normalized["created_at"] = jobs[idx].get("created_at", now)
        jobs[idx] = normalized
    else:
        jobs.append(normalized)

    atomic_write_json(BACKUP_JOBS_FILE, jobs)
    logger.info(f"[HYPER-BACKUP] Saved job {job_id} ('{normalized['name']}')")
    return normalized


def delete_backup_job(job_id: str) -> bool:
    """Deletes a scheduled hyper-backup job."""
    jobs = get_backup_jobs()
    filtered = [j for j in jobs if j.get("id") != job_id]
    if len(filtered) != len(jobs):
        atomic_write_json(BACKUP_JOBS_FILE, filtered)
        logger.info(f"[HYPER-BACKUP] Deleted job {job_id}")
        return True
    return False


def get_backup_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieves recent backup run history."""
    history = read_json(BACKUP_HISTORY_FILE, default=[])
    if not isinstance(history, list):
        return []
    history.sort(key=lambda x: x.get("started_at", 0), reverse=True)
    return history[:limit]


def record_backup_history(record: Dict[str, Any]) -> None:
    """Appends an execution record to the history log."""
    history = read_json(BACKUP_HISTORY_FILE, default=[])
    if not isinstance(history, list):
        history = []
    history.insert(0, record)
    history = history[:150]  # Cap at recent 150 entries
    atomic_write_json(BACKUP_HISTORY_FILE, history)


def prune_job_snapshots(pool_id: str, subvol_name: str, retention_count: int) -> List[str]:
    """Enforces rotation policy by deleting oldest snapshots exceeding retention_count."""
    if retention_count <= 0 or not subvol_name:
        return []
    pal = get_storage_platform()
    pruned: List[str] = []
    try:
        snapshots = pal.list_snapshots(pool_id)
        # Match snapshots targeting this subvolume
        prefix = f"{subvol_name}_"
        matching = [s for s in snapshots if s.get("name", "").startswith(prefix)]
        # Sort oldest first
        matching.sort(key=lambda x: x.get("created_at", 0) or x.get("name", ""))

        if len(matching) > retention_count:
            excess = len(matching) - retention_count
            for to_delete in matching[:excess]:
                snap_name = to_delete.get("name")
                if snap_name:
                    logger.info(f"[HYPER-BACKUP] Pruning excess snapshot: {snap_name}")
                    pal.delete_snapshot(pool_id, snap_name)
                    pruned.append(snap_name)
    except Exception as e:
        logger.warning(f"[HYPER-BACKUP] Snapshot pruning error: {e}")
    return pruned


def execute_backup_job(job_id: str) -> Dict[str, Any]:
    """Executes a hyper-backup pipeline: atomic snapshot + Rclone offsite sync + retention pruning."""
    jobs = get_backup_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        raise ValueError(f"Job with ID '{job_id}' not found.")

    start_time = time.time()
    subvol = job.get("source_subvolume", "").strip()
    pool_id = job.get("source_pool", "default")
    dest_type = job.get("destination_type", "remote")
    remote_name = job.get("remote_name", "").strip()
    remote_path = job.get("remote_path", "").strip()
    retention = job.get("retention_count", 7)

    # Update job state to running
    job["last_status"] = "running"
    save_backup_job(job)

    history_record: Dict[str, Any] = {
        "id": str(uuid.uuid4())[:8],
        "job_id": job_id,
        "job_name": job.get("name", "Unnamed Job"),
        "started_at": start_time,
        "completed_at": None,
        "status": "running",
        "snapshot_name": None,
        "pruned_snapshots": [],
        "rclone_job_id": None,
        "error": None,
    }

    pal = get_storage_platform()
    snap_result = None
    snap_name = None

    try:
        # Step 1: Create atomic local filesystem snapshot
        if subvol:
            snap_name = f"{subvol}_{time.strftime('%Y%m%d_%H%M%S')}"
            try:
                snap_result = pal.create_snapshot(
                    pool_id=pool_id,
                    subvol_name=subvol,
                    snapshot_name=snap_name,
                    readonly=True,
                )
                history_record["snapshot_name"] = snap_name
                logger.info(f"[HYPER-BACKUP] Created atomic snapshot: {snap_name} ({snap_result.get('status')})")
            except PlatformCapabilityError as pce:
                logger.info(f"[HYPER-BACKUP] Platform in observer mode ({pce}); skipping local snapshot.")
                history_record["snapshot_name"] = f"skipped ({pce})"

            # Prune older snapshots
            pruned = prune_job_snapshots(pool_id, subvol, retention)
            history_record["pruned_snapshots"] = pruned

        # Step 2: Trigger Rclone offsite sync if configured
        if dest_type == "remote" and remote_name:
            # Determine source path
            pool_path = pal.get_pool_path(pool_id)
            source_dir = os.path.join(pool_path, "@shares", subvol) if subvol else pool_path
            if not os.path.exists(source_dir):
                source_dir = os.path.join(pool_path, subvol) if subvol else pool_path

            dest_target = f"{remote_name}:{remote_path}"
            rclone = get_rclone_engine()
            sync_job = rclone.start_sync_job(
                src=source_dir,
                dst=dest_target,
                action="sync",
            )
            history_record["rclone_job_id"] = sync_job.get("id")
            logger.info(f"[HYPER-BACKUP] Dispatched Rclone offsite sync to {dest_target} (Job: {sync_job.get('id')})")

        # Mark job run success
        job["last_run_at"] = time.time()
        job["last_status"] = "success"
        job["last_error"] = None
        save_backup_job(job)

        history_record["completed_at"] = time.time()
        history_record["status"] = "success"
        record_backup_history(history_record)
        return history_record

    except Exception as e:
        logger.error(f"[HYPER-BACKUP] Execution error on job {job_id}: {e}")
        job["last_run_at"] = time.time()
        job["last_status"] = "error"
        job["last_error"] = str(e)
        save_backup_job(job)

        history_record["completed_at"] = time.time()
        history_record["status"] = "error"
        history_record["error"] = str(e)
        record_backup_history(history_record)
        return history_record


# =========================================================================
# Background Scheduler Daemon
# =========================================================================

_SCHEDULER_RUNNING = False
_SCHEDULER_THREAD: Optional[threading.Thread] = None

SCHEDULE_INTERVALS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
}


def _backup_scheduler_loop() -> None:
    """Checks every 60s for due backup jobs and launches them asynchronously."""
    logger.info("[HYPER-BACKUP] Scheduler daemon started.")
    while _SCHEDULER_RUNNING:
        try:
            jobs = get_backup_jobs()
            now = time.time()
            for job in jobs:
                if not job.get("enabled", True):
                    continue
                sched = job.get("schedule", "manual")
                interval = SCHEDULE_INTERVALS.get(sched)
                if not interval:
                    continue  # manual or unsupported schedule
                last_run = job.get("last_run_at") or 0
                if now - last_run >= interval:
                    logger.info(f"[HYPER-BACKUP] Job '{job.get('name')}' is due (schedule: {sched}). Executing...")
                    # Run in separate thread to prevent scheduler loop blocking
                    threading.Thread(
                        target=execute_backup_job,
                        args=(job["id"],),
                        daemon=True,
                        name=f"BackupJob-{job['id']}",
                    ).start()
        except Exception as e:
            logger.error(f"[HYPER-BACKUP] Scheduler iteration error: {e}")

        # Sleep in short increments for responsive stopping
        for _ in range(60):
            if not _SCHEDULER_RUNNING:
                break
            time.sleep(1)

    logger.info("[HYPER-BACKUP] Scheduler daemon stopped.")


def start_backup_scheduler() -> None:
    """Starts the background hyper-backup scheduler daemon if not already running."""
    global _SCHEDULER_RUNNING, _SCHEDULER_THREAD
    if _SCHEDULER_RUNNING:
        return
    _SCHEDULER_RUNNING = True
    _SCHEDULER_THREAD = threading.Thread(target=_backup_scheduler_loop, daemon=True, name="HyperBackupScheduler")
    _SCHEDULER_THREAD.start()


def stop_backup_scheduler() -> None:
    """Stops the background hyper-backup scheduler daemon."""
    global _SCHEDULER_RUNNING
    _SCHEDULER_RUNNING = False
