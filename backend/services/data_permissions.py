"""
Keeps credentials in DATA_DIR private to the container's user (SEC-14).

On hosts like Unraid the appdata share is often world-readable (and
browsable over SMB), which exposed the session-signing key, password
hashes and remote credentials. Run at every start; it only tightens.
"""

import logging
import os
import stat

from backend import config

logger = logging.getLogger("ZettNAS")

SECRET_FILES = (
    "secret.key",
    "security.json",
    "users.db",
    "users.db-wal",
    "users.db-shm",
    "ai_conversations.db",
    "ai_conversations.db-wal",
    "ai_conversations.db-shm",
    "webdav_config.json",
    "auth_lockout.json",
    "notifications.json",
    "notification_config.json",
    "network_config.json",
    "rag_config.json",
    "ups_config.json",
    "ups_config.backup.json",
    "sessions.json",
    "sessions.json.bak",
)
# Folders holding remote credentials or SSH host keys.
SECRET_DIRS = ("rclone", "sftp")


def _restrict(path: str, mode: int) -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return False
    if stat.S_IMODE(st.st_mode) & ~mode:
        try:
            os.chmod(path, stat.S_IMODE(st.st_mode) & mode)
            return True
        except OSError as e:
            logger.warning(f"[Permissions] Could not restrict {path}: {e}")
    return False


def harden_data_permissions(data_dir: str = "") -> int:
    """Removes group/other access from secret files and folders. Returns how many changed."""
    base = data_dir or config.DATA_DIR
    changed = 0
    for name in SECRET_FILES:
        changed += _restrict(os.path.join(base, name), 0o600)
    for name in SECRET_DIRS:
        root = os.path.join(base, name)
        if not os.path.isdir(root) or os.path.islink(root):
            continue
        changed += _restrict(root, 0o700)
        for dirpath, dirnames, filenames in os.walk(root):
            for d in dirnames:
                changed += _restrict(os.path.join(dirpath, d), 0o700)
            for f in filenames:
                changed += _restrict(os.path.join(dirpath, f), 0o600)
    if changed:
        logger.info(f"[Permissions] Restricted access to {changed} secret file(s)/folder(s) in {base}")
    return changed
