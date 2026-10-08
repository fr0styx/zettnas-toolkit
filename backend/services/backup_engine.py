"""
ZettNAS Toolkit - Backup Engine Service
Handles generation and safe restoration of configuration archives.
"""

import io
import os
import zipfile
from typing import BinaryIO

from backend.config import DATA_DIR, logger

# Files to exclude from backups
BACKUP_EXCLUSIONS = {
    "history.db",
    "history.db-shm",
    "history.db-wal",
    "sessions.json",
    "api_tokens.json",
}

MAX_RESTORE_BYTES = 50 * 1024 * 1024  # 50MB max cumulative restore size
MAX_MEMBER_COUNT = 1000


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
