"""
ZettNAS Toolkit - Backup Engine Service
Handles generation and safe restoration of configuration archives.
"""

import io
import os
import time
import zipfile
from typing import BinaryIO, Generator

from backend.config import DATA_DIR, logger

# Files to exclude from backups
BACKUP_EXCLUSIONS = {
    "history.db",
    "history.db-shm",
    "history.db-wal",
    "sessions.json",
}


def generate_backup_zip_stream() -> io.BytesIO:
    """Generates an in-memory zip archive of configuration files in DATA_DIR.

    Excludes volatile database histories and session tokens.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(DATA_DIR):
            for file in files:
                if file in BACKUP_EXCLUSIONS:
                    continue
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, DATA_DIR)
                z.write(file_path, rel_path)
    buf.seek(0)
    return buf


def restore_backup_archive(archive_file: BinaryIO) -> None:
    """Safely extracts a backup zip archive into DATA_DIR.

    Performs zip-slip validation to ensure no files escape DATA_DIR.
    """
    target_dir = os.path.abspath(DATA_DIR)
    os.makedirs(target_dir, exist_ok=True)

    with zipfile.ZipFile(archive_file, "r") as z:
        for member in z.infolist():
            # Validate target path
            extracted_path = os.path.abspath(os.path.join(target_dir, member.filename))
            # Zip slip guard
            if not extracted_path.startswith(target_dir + os.sep) and extracted_path != target_dir:
                raise ValueError(f"Illegal path in archive: {member.filename}")

        # Safe to extract
        z.extractall(target_dir)

    logger.info("[BACKUP] Configuration restored successfully from backup archive.")
