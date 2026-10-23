"""
ZettNAS Toolkit - Backup Engine Service
Handles generation and safe restoration of configuration archives,
plus Hyper-Backup 3-2-1 automated pipelines (snapshots + Rclone offsite sync)
and background scheduling.
"""

import io
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from typing import Any, BinaryIO, Optional

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json
from backend.hardware.pal_storage import PlatformCapabilityError, get_storage_platform
from backend.services.rclone_engine import get_rclone_engine

# -------------------------------------------------------------------------
# Configuration backup ("app-config" export): users, settings, shares, stacks,
# remotes and VM definitions in one archive, optionally encrypted.
# -------------------------------------------------------------------------

# Top-level files never exported: histories, live state, legacy credential
# stores and the AI search index (large and rebuildable).
BACKUP_EXCLUSIONS = {
    "history.db",
    "history.db-shm",
    "history.db-wal",
    "users.db-shm",
    "users.db-wal",
    "sessions.json",
    "sessions.json.bak",
    "api_tokens.json",
    "auth_lockout.json",
    "auth_lockout.json.lock",
    "reindex_progress.json",
    "metrics.db",
    "rag_index.db",
    "rag_index.db-shm",
    "rag_index.db-wal",
    "ai_conversations.db-shm",
    "ai_conversations.db-wal",
}
SKIP_SUFFIXES = (".pyc", ".tmp", ".swp", ".png", ".bmp", ".jpg", ".py", ".lock", "-wal", "-shm")

HEAVY_BACKUP_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "isos",
    "app_backups",
    "vm_backups",
    "trash",
    "backups",
    "catalog_cache",
    "tailscale",
    "taildrop",
    "vfs_cache",
}
# VM folders hold disks; only their definitions and firmware/TPM state are exported.
VM_DIR = "vms"
VM_KEEP_SUFFIXES = (".json", ".fd", ".xml", ".conf", ".yaml", ".yml")
VM_MAX_FILE_BYTES = 16 * 1024 * 1024

MAX_RESTORE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_COUNT = 1000
MANIFEST_NAME = "zettnas-backup.json"
FORMAT_VERSION = 2
ENCRYPTED_MAGIC = b"ZETTBAK2"

BACKUP_JOBS_FILE = os.path.join(DATA_DIR, "backup_jobs.json")
BACKUP_HISTORY_FILE = os.path.join(DATA_DIR, "backup_history.json")


def _wanted(rel_path: str, size: int) -> bool:
    parts = rel_path.split(os.sep)
    name = parts[-1]
    if any(p in HEAVY_BACKUP_DIRS for p in parts[:-1]):
        return False
    if len(parts) == 1 and name in BACKUP_EXCLUSIONS:
        return False
    if name.endswith(SKIP_SUFFIXES) or name.startswith((".tmp-", ".DS_Store")):
        return False
    if parts[0] == VM_DIR:
        return name.endswith(VM_KEEP_SUFFIXES) and size <= VM_MAX_FILE_BYTES
    return True


def _snapshot_db_bytes(path: str, clear_tables: tuple = ()) -> bytes:
    """Consistent copy of a SQLite database, with some tables emptied in the copy.

    An encrypted AI database (AI-20) is copied encrypted, so the backup needs the same
    ZETTNAS_DATA_KEY to restore and never holds its contents in plain text."""
    from backend import db_crypto

    if db_crypto.applies_to(path) and db_crypto.is_encrypted(path):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, os.path.basename(path))
            db_crypto.copy(path, out)
            with open(out, "rb") as f:
                return f.read()
    mem = sqlite3.connect(":memory:")
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10.0) as src:
            src.backup(mem)
        for table in clear_tables:
            try:
                mem.execute(f"DELETE FROM {table}")
            except sqlite3.Error:
                pass
        mem.commit()
        return mem.serialize()
    finally:
        mem.close()


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))


def encrypt_backup(data: bytes, passphrase: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, nonce = os.urandom(16), os.urandom(12)
    return ENCRYPTED_MAGIC + salt + nonce + AESGCM(_derive_key(passphrase, salt)).encrypt(nonce, data, ENCRYPTED_MAGIC)


def decrypt_backup(blob: bytes, passphrase: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(ENCRYPTED_MAGIC):
        raise ValueError("Not an encrypted ZettNAS backup")
    if not passphrase:
        raise ValueError("This backup is encrypted: enter its passphrase")
    head = len(ENCRYPTED_MAGIC)
    salt, nonce, ct = blob[head : head + 16], blob[head + 16 : head + 28], blob[head + 28 :]
    try:
        return AESGCM(_derive_key(passphrase, salt)).decrypt(nonce, ct, ENCRYPTED_MAGIC)
    except InvalidTag as e:
        raise ValueError("Wrong passphrase, or the backup file is damaged") from e


def generate_backup_zip_stream(passphrase: str = "") -> Any:
    """Builds the configuration backup (zip, or encrypted when a passphrase is given).

    Includes users (password hashes, roles, 2FA) without sessions or API tokens,
    settings, share/NFS/SFTP/rclone configuration, compose stacks, VM definitions
    and firmware state, and the install's secret key (needed to read encrypted
    2FA secrets). Excludes histories, caches, the AI search index, VM disks and ISOs.
    """
    from backend import __version__

    try:
        from backend.db_schema import SCHEMA_VERSIONS
    except Exception:
        SCHEMA_VERSIONS = {}

    spool = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)  # noqa: SIM115
    files: list[str] = []
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, names in os.walk(DATA_DIR):
            dirs[:] = [d for d in dirs if d not in HEAVY_BACKUP_DIRS and not os.path.islink(os.path.join(root, d))]
            for name in names:
                file_path = os.path.join(root, name)
                if os.path.islink(file_path):
                    continue
                rel_path = os.path.relpath(file_path, DATA_DIR)
                try:
                    size = os.path.getsize(file_path)
                except OSError:
                    continue
                if not _wanted(rel_path, size):
                    continue
                if name.endswith(".db"):
                    try:
                        clear = ("sessions", "api_tokens") if rel_path == "users.db" else ()
                        z.writestr(rel_path, _snapshot_db_bytes(file_path, clear))
                        files.append(rel_path)
                        continue
                    except Exception as e:
                        logger.debug(f"[BACKUP] Snapshot of {rel_path} fell back to a copy: {e}")
                z.write(file_path, rel_path)
                files.append(rel_path)
        manifest = {
            "format": FORMAT_VERSION,
            "app_version": __version__,
            "created_at": time.time(),
            "schema_versions": {k: v[0] for k, v in SCHEMA_VERSIONS.items()},
            "encrypted": bool(passphrase),
            "files": files,
        }
        z.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
    spool.seek(0)
    if not passphrase:
        return spool
    data = spool.read()
    spool.close()
    out = tempfile.SpooledTemporaryFile(max_size=10 * 1024 * 1024)  # noqa: SIM115
    out.write(encrypt_backup(data, passphrase))
    out.seek(0)
    return out


def _check_archive_schema(z: "zipfile.ZipFile", names: set) -> None:
    """Refuses a backup whose databases come from a newer ZettNAS than this one."""
    try:
        from backend.db_schema import SCHEMA_VERSIONS
    except Exception:
        return
    for name, (known, _rebuildable) in SCHEMA_VERSIONS.items():
        if name not in names:
            continue
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            tmp.write(z.read(name))
            tmp.flush()
            from backend import db_crypto

            try:
                if db_crypto.applies_to(name) and db_crypto.is_encrypted(tmp.name):
                    if not db_crypto.enabled():
                        raise ValueError(
                            f"The backup's {name} is encrypted; set the ZETTNAS_DATA_KEY it was made with first"
                        )
                    conn = db_crypto.connect_encrypted(tmp.name)
                else:
                    conn = sqlite3.connect(f"file:{tmp.name}?mode=ro", uri=True)
                found = int(conn.execute("PRAGMA user_version").fetchone()[0])
                conn.close()
            except db_crypto.errors() + (db_crypto.DataKeyError,):
                raise ValueError(
                    f"{name} in the backup is not a valid database, or was encrypted with another key"
                ) from None
        if found > known:
            raise ValueError(f"The backup's {name} comes from a newer ZettNAS (schema v{found}); update first")


def restore_backup_archive(archive_file: BinaryIO, passphrase: str = "", snapshot: bool = True) -> dict[str, Any]:
    """Validates and restores a configuration backup into DATA_DIR.

    Rejects zip-slip paths, symlinks, oversized archives and databases from a
    newer version; restores only what an export can contain; saves the current
    data to data/backups/pre-update/ first; and ends every session afterwards.
    """
    target_dir = os.path.abspath(DATA_DIR)
    os.makedirs(target_dir, exist_ok=True)

    head = archive_file.read(len(ENCRYPTED_MAGIC))
    archive_file.seek(0)
    if head == ENCRYPTED_MAGIC:
        blob = archive_file.read(MAX_RESTORE_BYTES + 1024)
        archive_file = io.BytesIO(decrypt_backup(blob, passphrase))

    with zipfile.ZipFile(archive_file, "r") as z:
        members = z.infolist()
        if len(members) > MAX_MEMBER_COUNT:
            raise ValueError(f"Backup archive exceeds maximum allowable file count ({MAX_MEMBER_COUNT})")

        total_size = 0
        selected = []
        for member in members:
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Symlinks are forbidden in backup archive: {member.filename}")
            total_size += member.file_size
            if total_size > MAX_RESTORE_BYTES:
                raise ValueError("Backup archive exceeds maximum allowable uncompressed size (256MB)")
            extracted_path = os.path.abspath(os.path.join(target_dir, member.filename))
            if not extracted_path.startswith(target_dir + os.sep) and extracted_path != target_dir:
                raise ValueError(f"Illegal path in archive: {member.filename}")
            rel = os.path.relpath(extracted_path, target_dir)
            if member.is_dir() or member.filename == MANIFEST_NAME:
                continue
            if _wanted(rel, member.file_size):
                selected.append(member)

        _check_archive_schema(z, {m.filename for m in selected})

        snapshot_path = None
        if snapshot:
            try:
                from backend.services.data_snapshot import take_snapshot

                snapshot_path = take_snapshot(target_dir, label="pre-restore", extra={"kind": "restore"})
            except Exception as e:
                raise ValueError(f"Could not save the current data before restoring: {e}") from e

        for member in selected:
            dst = os.path.join(target_dir, member.filename)
            for suffix in ("-wal", "-shm"):
                if member.filename.endswith(".db") and os.path.exists(dst + suffix):
                    os.remove(dst + suffix)
            z.extract(member, target_dir)

    # Sessions and API tokens from the backup's users DB (older exports kept them)
    # must not come back.
    if any(m.filename == "users.db" for m in selected):
        try:
            from backend.users_db import _SESSION_CACHE, _SESSION_CACHE_LOCK, _TOKEN_CACHE, _TOKEN_CACHE_LOCK

            with sqlite3.connect(os.path.join(target_dir, "users.db"), timeout=15.0) as conn:
                for table in ("sessions", "api_tokens"):
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except sqlite3.Error:
                        pass
            with _SESSION_CACHE_LOCK:
                _SESSION_CACHE.clear()
            with _TOKEN_CACHE_LOCK:
                _TOKEN_CACHE.clear()
        except Exception as e:
            logger.warning(f"[BACKUP] Could not reset sessions after restore: {e}")

    logger.info(f"[BACKUP] Restored {len(selected)} file(s) from a configuration backup.")
    return {"restored": len(selected), "snapshot": snapshot_path}


# =========================================================================
# Hyper-Backup Orchestrator: Jobs, Snapshots & 3-2-1 Cloud Sync
# =========================================================================


def get_backup_jobs() -> list[dict[str, Any]]:
    """Retrieves all scheduled hyper-backup jobs."""
    raw = read_json(BACKUP_JOBS_FILE, default=[])
    if isinstance(raw, list):
        return raw
    return []


def save_backup_job(job_data: dict[str, Any]) -> dict[str, Any]:
    """Creates or updates a scheduled hyper-backup job."""
    jobs = get_backup_jobs()
    job_id = job_data.get("id") or str(uuid.uuid4())[:8]
    now = time.time()

    normalized: dict[str, Any] = {
        "id": job_id,
        "name": job_data.get("name", "Untitled Backup Task").strip() or "Untitled Backup Task",
        "source_pool": job_data.get("source_pool", "default"),
        "source_subvolume": job_data.get("source_subvolume", "").strip(),
        "destination_type": job_data.get("destination_type", "remote"),  # "remote" or "local_snapshot"
        "remote_name": job_data.get("remote_name", "").strip(),
        "remote_path": job_data.get("remote_path", "").strip(),
        "schedule": job_data.get("schedule", "daily"),  # "hourly", "daily", "weekly", "manual"
        "retention_count": max(1, int(job_data.get("retention_count", 7))),
        "encryption_enabled": bool(job_data.get("encryption_enabled", False)),
        "encryption_mode": str(job_data.get("encryption_mode", "none")),  # "none", "rclone_crypt", "aes256"
        "bandwidth_limit_kbps": int(job_data.get("bandwidth_limit_kbps", 0)),
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


def get_backup_history(limit: int = 50) -> list[dict[str, Any]]:
    """Retrieves recent backup run history."""
    history = read_json(BACKUP_HISTORY_FILE, default=[])
    if not isinstance(history, list):
        return []
    history.sort(key=lambda x: x.get("started_at", 0), reverse=True)
    return history[:limit]


def record_backup_history(record: dict[str, Any]) -> None:
    """Appends an execution record to the history log."""
    history = read_json(BACKUP_HISTORY_FILE, default=[])
    if not isinstance(history, list):
        history = []
    history.insert(0, record)
    history = history[:150]  # Cap at recent 150 entries
    atomic_write_json(BACKUP_HISTORY_FILE, history)


def prune_job_snapshots(pool_id: str, subvol_name: str, retention_count: int) -> list[str]:
    """Enforces rotation policy by deleting oldest snapshots exceeding retention_count."""
    if retention_count <= 0 or not subvol_name:
        return []
    pal = get_storage_platform()
    pruned: list[str] = []
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


def execute_backup_job(job_id: str) -> dict[str, Any]:
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

    history_record: dict[str, Any] = {
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
            # Determine source path - prioritize read-only snapshot directory for atomic point-in-time consistency
            source_dir = None
            if snap_result and isinstance(snap_result, dict):
                source_dir = snap_result.get("snapshot_path") or snap_result.get("path")
            if not source_dir or not os.path.exists(source_dir):
                pool_path = pal.get_pool_path(pool_id)
                source_dir = os.path.join(pool_path, "@shares", subvol) if subvol else pool_path
                if not os.path.exists(source_dir):
                    source_dir = os.path.join(pool_path, subvol) if subvol else pool_path

            dest_target = f"{remote_name}:{remote_path}"
            rclone = get_rclone_engine()

            # Client-side rclone crypt encryption wrapper
            if job.get("encrypted") and job.get("encryption_password"):
                crypt_remote_name = f"crypt_{job_id[:8]}"
                try:
                    rclone.create_crypt_remote(
                        name=crypt_remote_name,
                        base_remote_path=dest_target,
                        password=job["encryption_password"],
                    )
                    dest_target = f"{crypt_remote_name}:"
                    logger.info(f"[HYPER-BACKUP] Initialized client-side encrypted crypt overlay: {dest_target}")
                except Exception as crypt_err:
                    logger.warning(
                        f"[HYPER-BACKUP] Failed creating crypt overlay, falling back to base remote: {crypt_err}"
                    )

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

        # Dispatch multi-channel notification
        if job.get("notify", True):
            try:
                from backend.services.notifications import send_notification

                dest_desc = f" -> {dest_target}" if (dest_type == "remote" and remote_name) else ""
                send_notification(
                    {
                        "type": "backup",
                        "title": f"Hyper-Backup Succeeded: {job.get('name', job_id)}",
                        "message": f"Backup job '{job.get('name', job_id)}' completed successfully{dest_desc}."
                        + (f" Snapshot: {snap_name}" if snap_name else ""),
                        "level": "info",
                        "meta": {"job_id": job_id, "snapshot": snap_name, "pool": pool_id},
                    }
                )
            except Exception as notify_err:
                logger.debug(f"[HYPER-BACKUP] Notification dispatch error: {notify_err}")

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

        if job.get("notify", True):
            try:
                from backend.services.notifications import send_notification

                send_notification(
                    {
                        "type": "backup",
                        "title": f"Hyper-Backup Failed: {job.get('name', job_id)}",
                        "message": f"Backup job '{job.get('name', job_id)}' failed: {str(e)}",
                        "level": "error",
                        "meta": {"job_id": job_id, "error": str(e), "pool": pool_id},
                    }
                )
            except Exception as notify_err:
                logger.debug(f"[HYPER-BACKUP] Failure notification dispatch error: {notify_err}")

        return history_record


# =========================================================================
# Background Scheduler Daemon
# =========================================================================

_SCHEDULER_RUNNING = False
_SCHEDULER_THREAD: threading.Thread | None = None

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
