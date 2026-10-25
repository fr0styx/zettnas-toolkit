"""
Rotating the install's secret key (audit batch 0/1 follow-up).

The secret key encrypts two-factor secrets and backup passphrases, and signs short-lived
tokens. If someone may have copied it, a superadmin replaces it here: everything encrypted
with it is decrypted with the old key and encrypted again with a new one.

Crash-safe: the old key is written to secret.key.previous before anything changes, and
reading falls back to it, so data is readable whichever key it carries until the rotation
finishes and the previous key is removed.
"""

import logging
import os
import secrets
import time
from typing import Any

from backend import config

logger = logging.getLogger("ZettNAS")


def previous_key_file() -> str:
    return config.SECRET_KEY_FILE + ".previous"


def _write_owner_only(path: str, text: str) -> None:
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def rotate_secret_key() -> dict[str, Any]:
    """Replaces the secret key and re-encrypts what it protects. Returns counts."""
    if os.environ.get("SECRET_KEY", "").strip():
        raise ValueError("The secret key is set by the SECRET_KEY environment variable; change it there.")
    from backend import secret_box
    from backend.fsutil import atomic_write_json, locked_json
    from backend.services.backup_engine import BACKUP_JOBS_FILE, get_backup_jobs
    from backend.users_db import _evict_user_caches, users_db_session

    old_key = str(config.SECRET_KEY or "")
    new_key = secrets.token_hex(32)
    _write_owner_only(previous_key_file(), old_key)
    _write_owner_only(config.SECRET_KEY_FILE, new_key)
    config.SECRET_KEY = new_key

    resealed_mfa = 0
    with users_db_session(None) as conn:
        rows = conn.execute(
            "SELECT id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL AND mfa_secret != ''"
        ).fetchall()
        for row in rows:
            value = str(row["mfa_secret"])
            if not secret_box.is_sealed(value):
                continue
            plain = secret_box.unseal(value)  # falls back to the previous key
            conn.execute("UPDATE users SET mfa_secret = ? WHERE id = ?", (secret_box.seal(plain), row["id"]))
            resealed_mfa += 1
    for row in rows:
        _evict_user_caches(row["id"])

    resealed_backups = 0
    with locked_json(BACKUP_JOBS_FILE):
        jobs = get_backup_jobs()
        for job in jobs:
            value = str(job.get("encryption_password") or "")
            if value and secret_box.is_sealed(value):
                job["encryption_password"] = secret_box.seal(secret_box.unseal(value))
                resealed_backups += 1
        if resealed_backups:
            atomic_write_json(BACKUP_JOBS_FILE, jobs)

    os.remove(previous_key_file())
    result = {"rotated_at": time.time(), "mfa_secrets": resealed_mfa, "backup_passphrases": resealed_backups}
    logger.warning(f"[Security] Secret key rotated: {result}")
    return result
