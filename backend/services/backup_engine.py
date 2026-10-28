"""
ZettNAS Toolkit - Backup Engine Service
Handles generation and safe restoration of configuration archives,
plus backup 3-2-1 automated pipelines (snapshots + Rclone offsite sync)
and background scheduling.
"""

import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import zipfile
from typing import Any, BinaryIO, Optional

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json, read_json_cached, resolve_within
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


STAGED_RESTORE_DIR = ".restore-staged"
STAGED_MANIFEST = "staged.json"


def _clear_sessions_and_tokens(users_db: str) -> None:
    """Sessions and API tokens from the backup's users DB (older exports kept them) must not come back."""
    from backend.users_db import _SESSION_CACHE, _SESSION_CACHE_LOCK, _TOKEN_CACHE, _TOKEN_CACHE_LOCK

    with sqlite3.connect(users_db, timeout=15.0) as conn:
        for table in ("sessions", "api_tokens"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.Error:
                logger.debug(f"[BACKUP] no {table} table to clear", exc_info=True)
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.clear()
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()


def apply_staged_restore(data_dir: str) -> list[str]:
    """Moves a staged settings restore into place. Run at start, before any database is opened (REL-3)."""
    staged = os.path.join(data_dir, STAGED_RESTORE_DIR)
    manifest = os.path.join(staged, STAGED_MANIFEST)
    files = read_json(manifest, None)
    if not os.path.isdir(staged):
        return []
    if not isinstance(files, list):
        shutil.rmtree(staged, ignore_errors=True)  # an interrupted staging: nothing to apply
        return []
    moved = []
    for rel in files:
        src, dst = os.path.join(staged, rel), os.path.join(data_dir, rel)
        if not os.path.isfile(src):
            continue
        for suffix in ("-wal", "-shm"):
            if dst.endswith(".db") and os.path.exists(dst + suffix):
                os.remove(dst + suffix)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        moved.append(rel)
    if "users.db" in moved:
        try:
            _clear_sessions_and_tokens(os.path.join(data_dir, "users.db"))
        except Exception as e:
            logger.warning(f"[BACKUP] Could not reset sessions after restore: {e}")
    shutil.rmtree(staged, ignore_errors=True)
    logger.warning(f"[BACKUP] Applied a staged settings restore: {len(moved)} file(s)")
    try:
        from backend.state import add_event

        add_event("success", "Settings restored", f"The settings backup was applied ({len(moved)} files).")
    except Exception:
        logger.debug("[BACKUP] could not record the restore event", exc_info=True)
    return moved


def restore_backup_archive(
    archive_file: BinaryIO, passphrase: str = "", snapshot: bool = True, staged: bool = False
) -> dict[str, Any]:
    """Validates and restores a configuration backup into DATA_DIR.

    Rejects zip-slip paths, symlinks, oversized archives and databases from a
    newer version; restores only what an export can contain; saves the current
    data to data/backups/pre-update/ first; and ends every session afterwards.

    `staged` extracts into data/.restore-staged; the next start swaps it in before any database
    is opened, so a restore never writes over files the running app has open (REL-3).
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

        if staged:
            stage_dir = os.path.join(target_dir, STAGED_RESTORE_DIR)
            shutil.rmtree(stage_dir, ignore_errors=True)
            os.makedirs(stage_dir, mode=0o700)
            for member in selected:
                z.extract(member, stage_dir)
            atomic_write_json(os.path.join(stage_dir, STAGED_MANIFEST), [m.filename for m in selected])
            logger.info(f"[BACKUP] Staged {len(selected)} file(s); they are applied at the next start.")
            return {"restored": len(selected), "snapshot": snapshot_path, "staged": True}

        for member in selected:
            dst = os.path.join(target_dir, member.filename)
            for suffix in ("-wal", "-shm"):
                if member.filename.endswith(".db") and os.path.exists(dst + suffix):
                    os.remove(dst + suffix)
            z.extract(member, target_dir)

    if any(m.filename == "users.db" for m in selected):
        try:
            _clear_sessions_and_tokens(os.path.join(target_dir, "users.db"))
        except Exception as e:
            logger.warning(f"[BACKUP] Could not reset sessions after restore: {e}")

    logger.info(f"[BACKUP] Restored {len(selected)} file(s) from a configuration backup.")
    return {"restored": len(selected), "snapshot": snapshot_path}


# =========================================================================
# backup Orchestrator: Jobs, Snapshots & 3-2-1 Cloud Sync
# =========================================================================


def get_backup_jobs() -> list[dict[str, Any]]:
    """Retrieves all scheduled backup jobs."""
    raw = read_json(BACKUP_JOBS_FILE, default=[])
    if isinstance(raw, list):
        return raw
    return []


def checked_subvolume(value: Any) -> str:
    """A backup source: empty (the whole pool) or a relative folder path inside the pool."""
    raw = str(value or "").strip()
    parts = [x for x in raw.split("/") if x]
    if raw.startswith("/") or "\\" in raw or any(x in (".", "..") for x in parts):
        raise ValueError("The backup source must be a folder inside the pool.")
    return "/".join(parts)


CONFIG_EXPORT_PREFIX = "zettnas_backup_"
MIN_PASSPHRASE = 8


def _settings_job_checks(job_data: dict[str, Any], password: str) -> None:
    """A ZettNAS-settings backup is always encrypted and goes to a pool folder or an rclone remote (OPS-8)."""
    from backend import config

    if len(password) < MIN_PASSPHRASE:
        raise ValueError(f"A settings backup needs a passphrase of at least {MIN_PASSPHRASE} characters.")
    dest = job_data.get("destination_type")
    if dest == "local_folder":
        if not resolve_within(str(job_data.get("local_path") or ""), config.ALLOWED_BROWSE_ROOTS):
            raise ValueError("The destination folder must be inside the storage folders.")
    elif dest == "remote":
        if not str(job_data.get("remote_name") or "").strip():
            raise ValueError("Choose an rclone remote for the settings backup.")
    else:
        raise ValueError("A settings backup goes to a folder in the pool or to an rclone remote.")


# A mirror deletes at the destination what is gone at the source. More deletions than this in one
# run (a stopped array, a renamed top folder, ransomware) stop the run instead (REL-1).
MAX_DELETE_PER_RUN = 1000
SYNC_POLL_SECONDS = 5.0
SYNC_MAX_WAIT_SECONDS = 48 * 3600

_RUNNING_JOBS: set[str] = set()
_RUNNING_LOCK = threading.Lock()


def _seal_passphrase(value: str) -> str:
    """Passphrases are stored encrypted with the install's secret key (SEC-5 follow-up)."""
    from backend import secret_box

    if not value or secret_box.is_sealed(value):
        return value
    return secret_box.seal(value)


def job_passphrase(job: dict[str, Any]) -> str:
    """The job's passphrase in clear text, for the moment it is used."""
    from backend import secret_box

    return secret_box.unseal(str(job.get("encryption_password") or ""))


@json_locked(lambda *a, **k: BACKUP_JOBS_FILE)
def _update_job_status(job_id: str, **fields: Any) -> None:
    """Writes status fields onto the job as it is now, so edits made during a run are kept (ARC-1)."""
    jobs = get_backup_jobs()
    for j in jobs:
        if j.get("id") == job_id:
            j.update(fields)
            atomic_write_json(BACKUP_JOBS_FILE, jobs)
            return


def _source_is_empty(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return next(it, None) is None
    except OSError:
        return True


VERSIONS_DIR = ".zettnas-versions"  # files a copy replaced, by run, at the destination (REL-9)
NO_NEW_COPY_JOBS = (
    "Folders now go to the cloud as an off-site backup (Backup, Off-site): it keeps versions and is "
    "encrypted. Copy jobs you already have keep running, and each can be moved there with one click."
)


def _versions_of(dest: str) -> str:
    return f"{dest}{VERSIONS_DIR}" if dest.endswith(":") else f"{dest.rstrip('/')}/{VERSIONS_DIR}"


def _prune_versions(rclone: Any, dest: str, keep: int) -> list[str]:
    """Keeps the folders of replaced files of the newest `keep` runs; returns the ones removed."""
    root = _versions_of(dest)
    try:
        runs = sorted(rclone.list_dirs(root))
        old = runs[: max(0, len(runs) - max(1, keep))]
        for name in old:
            rclone.purge(f"{root}/{name}")
        return old
    except Exception as e:  # the backup itself is done: old versions go next time
        logger.warning(f"[HYPER-BACKUP] Could not prune old versions at {root}: {e}")
        return []


def _writes_frozen() -> bool:
    try:
        from backend.services.ransomware_guard import get_guard

        return get_guard().frozen
    except Exception:
        logger.debug("backup_engine: ransomware guard unreadable", exc_info=True)
        return False


def _wait_for_sync(rclone: Any, sync_id: str) -> dict[str, Any]:
    """Waits for the upload to finish and returns its final state."""
    deadline = time.time() + SYNC_MAX_WAIT_SECONDS
    while time.time() < deadline:
        state = rclone.get_sync_job(sync_id) or {}
        if state.get("status") != "running":
            return state
        time.sleep(SYNC_POLL_SECONDS)
    return {"status": "error", "error": "The upload did not finish within 48 hours."}


@json_locked(lambda *a, **k: BACKUP_JOBS_FILE)
def save_backup_job(job_data: dict[str, Any]) -> dict[str, Any]:
    """Creates or updates a scheduled backup job."""
    kind = "config" if job_data.get("kind") == "config" else "data"
    if kind == "data":
        job_data = {**job_data, "source_subvolume": checked_subvolume(job_data.get("source_subvolume", ""))}
    else:
        job_data = {**job_data, "source_subvolume": ""}
    jobs = get_backup_jobs()
    job_id = job_data.get("id") or str(uuid.uuid4())[:8]
    now = time.time()
    existing = next((j for j in jobs if j.get("id") == job_id), {})
    # Editing a job without retyping its passphrase keeps the stored one
    password = str(job_data.get("encryption_password") or existing.get("encryption_password") or "")
    if kind == "config":
        from backend import secret_box

        _settings_job_checks(job_data, secret_box.unseal(password))

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
        "kind": kind,  # "data" (a pool folder) or "config" (ZettNAS settings, OPS-8)
        "local_path": str(job_data.get("local_path") or "").strip(),
        "encrypted": bool(job_data.get("encrypted", False)) or kind == "config",
        "encryption_password": _seal_passphrase(password),
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


@json_locked(lambda *a, **k: BACKUP_JOBS_FILE)
def delete_backup_job(job_id: str) -> bool:
    """Deletes a scheduled backup job."""
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


@json_locked(lambda *a, **k: BACKUP_HISTORY_FILE)
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


def _export_settings(job: dict[str, Any], retention: int) -> str:
    """Writes an encrypted ZettNAS settings backup to the job's folder or remote; returns where (OPS-8)."""
    from backend import config

    password = job_passphrase(job)
    if len(password) < MIN_PASSPHRASE:
        raise ValueError("This settings backup has no passphrase; edit the job and set one.")
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = f"{CONFIG_EXPORT_PREFIX}{ts}.zettbak"
    stream = generate_backup_zip_stream(passphrase=password)
    try:
        data = stream.read()
    finally:
        stream.close()
    if job.get("destination_type") == "local_folder":
        folder = resolve_within(str(job.get("local_path") or ""), config.ALLOWED_BROWSE_ROOTS)
        if not folder:
            raise ValueError("The destination folder must be inside the storage folders.")
        os.makedirs(folder, exist_ok=True)
        tmp = os.path.join(folder, f".{name}.tmp")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, os.path.join(folder, name))
        ours = sorted(n for n in os.listdir(folder) if n.startswith(CONFIG_EXPORT_PREFIX) and n.endswith(".zettbak"))
        for old in ours[: -max(1, int(retention))]:
            os.remove(os.path.join(folder, old))
        return os.path.join(folder, name)
    remote = str(job.get("remote_name") or "").strip()
    if not remote:
        raise ValueError("Choose an rclone remote or a folder for the settings backup.")
    outbox = os.path.join(DATA_DIR, "backups", "config-outbox")  # not part of backups or snapshots
    run_dir = os.path.join(outbox, ts)
    os.makedirs(run_dir, mode=0o700, exist_ok=True)
    with open(os.path.join(run_dir, name), "wb") as f:
        f.write(data)
    for old in sorted(os.listdir(outbox))[:-2]:  # the copy runs in the background: keep the last two
        shutil.rmtree(os.path.join(outbox, old), ignore_errors=True)
    remote_path = str(job.get("remote_path") or "").strip()
    rclone = get_rclone_engine()
    sync = rclone.start_sync_job(src=run_dir, dst=f"{remote}:{remote_path}", action="copy")
    final = _wait_for_sync(rclone, str(sync.get("id")))  # a success only once it is there (REL-9)
    if final.get("status") != "success":
        raise ValueError(f"The settings backup did not reach {remote}: {final.get('error') or 'the upload failed'}")
    return f"{remote}:{remote_path.rstrip('/')}/{name}"


def execute_backup_job(job_id: str) -> dict[str, Any]:
    """Executes a backup pipeline: atomic snapshot + Rclone offsite sync + retention pruning.

    One run per job at a time: a second start while it runs is refused (ARC-1)."""
    jobs = get_backup_jobs()
    job = next((j for j in jobs if j.get("id") == job_id), None)
    if not job:
        raise ValueError(f"Job with ID '{job_id}' not found.")
    with _RUNNING_LOCK:
        if job_id in _RUNNING_JOBS:
            raise ValueError("This backup is already running.")
        _RUNNING_JOBS.add(job_id)
    try:
        return _execute_backup_job(job)
    finally:
        with _RUNNING_LOCK:
            _RUNNING_JOBS.discard(job_id)


def is_job_running(job_id: str) -> bool:
    with _RUNNING_LOCK:
        return job_id in _RUNNING_JOBS


def _dump_databases(pal: Any, pool_id: str, subvol: str) -> list[dict[str, Any]]:
    """Database dumps for the folder a copy job reads (REL-20); a failure never stops the job."""
    try:
        from backend.services import backup_hooks

        pool_path = pal.get_pool_path(pool_id)
        paths = [os.path.join(pool_path, "@shares", subvol), os.path.join(pool_path, subvol)] if subvol else [pool_path]
        return backup_hooks.run_dumps([p for p in paths if os.path.isdir(p)])
    except Exception as e:
        logger.warning(f"[HYPER-BACKUP] Database dumps skipped: {e}")
        return []


def _execute_backup_job(job: dict[str, Any]) -> dict[str, Any]:
    job_id = str(job.get("id"))

    start_time = time.time()
    subvol = checked_subvolume(job.get("source_subvolume", ""))
    pool_id = job.get("source_pool", "default")
    dest_type = job.get("destination_type", "remote")
    remote_name = job.get("remote_name", "").strip()
    remote_path = job.get("remote_path", "").strip()
    retention = job.get("retention_count", 7)

    # Update job state to running; the start counts as the run for the schedule (ARC-1)
    job["last_status"] = "running"
    _update_job_status(job_id, last_status="running", last_started_at=start_time)

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

    if job.get("kind") != "config" and _writes_frozen():
        why = (
            "Skipped: the ransomware guard froze writes, so nothing was copied and the backup keeps "
            "the files from before. Unfreeze in Security once the shares are checked."
        )
        _update_job_status(job_id, last_status="skipped", last_error=why)
        history_record.update(completed_at=time.time(), status="skipped", error=why)
        record_backup_history(history_record)
        logger.warning(f"[HYPER-BACKUP] {job.get('name', job_id)}: {why}")
        return history_record

    pal = get_storage_platform()
    snap_result = None
    snap_name = None
    dest_target = ""

    try:
        if job.get("kind") == "config":
            history_record["snapshot_name"] = dest_target = _export_settings(job, retention)
        else:
            # Step 0: databases in the source write a dump first, so the snapshot holds one (REL-20)
            history_record["dumps"] = _dump_databases(pal, pool_id, subvol)
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
                    from backend.fsutil import resolve_within

                    if resolve_within(source_dir, [pool_path]) is None:
                        raise ValueError("The backup source is outside the pool.")

                # An empty or unmounted source would make the mirror delete the whole backup (REL-1)
                if _source_is_empty(source_dir):
                    raise ValueError(
                        "The backup source is empty or not mounted (is the array started?). "
                        "Nothing was changed at the destination."
                    )

                dest_target = f"{remote_name}:{remote_path}"
                rclone = get_rclone_engine()

                # Client-side rclone crypt encryption wrapper. If it can't be set up the run stops:
                # falling back would mirror plaintext over the encrypted copy (SEC-5).
                if job.get("encrypted") and job.get("encryption_password"):
                    crypt_remote_name = f"crypt_{job_id[:8]}"
                    try:
                        rclone.create_crypt_remote(
                            name=crypt_remote_name,
                            base_remote_path=dest_target,
                            password=job_passphrase(job),
                        )
                    except Exception as crypt_err:
                        raise ValueError(
                            f"Encryption for this backup could not be set up ({crypt_err}). "
                            "Nothing was uploaded and the existing backup is unchanged."
                        ) from crypt_err
                    dest_target = f"{crypt_remote_name}:"
                    logger.info(f"[HYPER-BACKUP] Initialized client-side encrypted crypt overlay: {dest_target}")

                # copy, never sync: a file deleted (or encrypted away) at home is never deleted
                # from the backup. Versions of changed files are what offsite backup (restic) is for.
                # A file the copy would replace is moved to .zettnas-versions/<run> first, so a file
                # encrypted at home never overwrites the good copy (REL-9)
                versions = f"{_versions_of(dest_target)}/{time.strftime('%Y%m%d-%H%M%S')}"
                sync_job = rclone.start_sync_job(
                    src=source_dir,
                    dst=dest_target,
                    action="copy",
                    extra_flags=[
                        "--max-delete",
                        str(MAX_DELETE_PER_RUN),
                        "--backup-dir",
                        versions,
                        "--exclude",
                        f"/{VERSIONS_DIR}/**",
                        "--exclude",
                        ".RecycleBin/**",
                    ],
                )
                history_record["rclone_job_id"] = sync_job.get("id")
                logger.info(
                    f"[HYPER-BACKUP] Dispatched Rclone offsite sync to {dest_target} (Job: {sync_job.get('id')})"
                )
                # The run succeeds only when the upload does (ARC-1)
                final = _wait_for_sync(rclone, str(sync_job.get("id")))
                if final.get("status") != "success":
                    detail = str(final.get("error") or "the upload failed")
                    log_text = " ".join(str(e.get("message", "")) for e in final.get("transfer_log") or []).lower()
                    if "max" in log_text and "delete" in log_text:
                        detail = (
                            f"more than {MAX_DELETE_PER_RUN} files would have been deleted from the backup; "
                            "the run stopped to protect it. Check the source folder."
                        )
                    raise ValueError(f"Upload to {dest_target} did not finish: {detail}")
                history_record["pruned_versions"] = _prune_versions(rclone, dest_target, int(retention))

        # Mark job run success
        job["last_run_at"] = time.time()
        job["last_status"] = "success"
        job["last_error"] = None
        _update_job_status(
            job_id,
            last_run_at=job["last_run_at"],
            last_success_at=job["last_run_at"],
            last_status="success",
            last_error=None,
        )

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
                        "title": f"Backup succeeded: {job.get('name', job_id)}",
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
        _update_job_status(job_id, last_run_at=job["last_run_at"], last_status="error", last_error=str(e))

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
                        "title": f"Backup failed: {job.get('name', job_id)}",
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
# set to stop the scheduler at once; it otherwise wakes once a minute, not every second (PERF-21)
_SCHEDULER_WAKE = threading.Event()
SCHEDULER_TICK_SECS = 60.0
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
            # read-only here, so the cached copy (re-read when the file changes; PERF-21)
            raw_jobs = read_json_cached(BACKUP_JOBS_FILE, [], max_age=SCHEDULER_TICK_SECS)
            jobs = raw_jobs if isinstance(raw_jobs, list) else []
            now = time.time()
            for job in jobs:
                if not job.get("enabled", True):
                    continue
                sched = job.get("schedule", "manual")
                interval = SCHEDULE_INTERVALS.get(sched)
                if not interval:
                    continue  # manual or unsupported schedule
                if is_job_running(str(job.get("id"))):
                    continue  # still running: never start it twice (ARC-1)
                last_run = max(job.get("last_run_at") or 0, job.get("last_started_at") or 0)
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

        from backend.services.supervisor import beat

        beat("BackupScheduler")
        # one wait a minute; stop_backup_scheduler sets the event to end it at once (PERF-21)
        if _SCHEDULER_WAKE.wait(SCHEDULER_TICK_SECS):
            _SCHEDULER_WAKE.clear()

    logger.info("[HYPER-BACKUP] Scheduler daemon stopped.")


@json_locked(lambda *a, **k: BACKUP_JOBS_FILE)
def mark_interrupted_jobs() -> list[str]:
    """At start: a backup still marked running was cut off by the restart (REL-18). It says so
    instead of looking busy forever, and runs again at its next time."""
    jobs = get_backup_jobs()
    cut = []
    for j in jobs:
        if j.get("last_status") == "running":
            j["last_status"] = "interrupted"
            j["last_error"] = "ZettNAS restarted while this backup was running; it runs again at its next time."
            cut.append(str(j.get("id")))
    if cut:
        atomic_write_json(BACKUP_JOBS_FILE, jobs)
        logger.warning(f"[HYPER-BACKUP] Marked interrupted at start: {', '.join(cut)}")
    return cut


def backup_scheduler_daemon() -> None:
    """The scheduler loop for the supervisor: restarted if it crashes (ARC-10)."""
    global _SCHEDULER_RUNNING
    _SCHEDULER_RUNNING = True
    _backup_scheduler_loop()


def start_backup_scheduler() -> None:
    """Starts the background backup scheduler daemon if not already running."""
    global _SCHEDULER_RUNNING, _SCHEDULER_THREAD
    if _SCHEDULER_RUNNING:
        return
    _SCHEDULER_RUNNING = True
    _SCHEDULER_THREAD = threading.Thread(target=_backup_scheduler_loop, daemon=True, name="HyperBackupScheduler")
    _SCHEDULER_THREAD.start()


def stop_backup_scheduler() -> None:
    """Stops the background backup scheduler daemon."""
    global _SCHEDULER_RUNNING
    _SCHEDULER_RUNNING = False
    _SCHEDULER_WAKE.set()
