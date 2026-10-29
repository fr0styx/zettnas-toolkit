"""Per-person spaces and their quotas (Batch 6).

Each person gets a private folder, <pool>/homes/<username> (only they and administrators
can open it; see path_access). On Btrfs it is a subvolume with a quota group, on ZFS (when the
homes folder is a dataset) a child dataset with a refquota, and on XFS with project quotas a
project: then the limit holds over SMB, NFS and WebDAV too (FEAT-10). Elsewhere ZettNAS checks
it on uploads it receives, and says so.
"""

import os
import subprocess
import threading
import time
from typing import Any

from backend import config
from backend.config import logger
from backend.fsutil import atomic_write_json, json_locked, read_json
from backend.hardware import fs_quota

_USAGE_TTL = 60.0
_usage_cache: dict[str, tuple[float, int]] = {}
_lock = threading.Lock()


class QuotaExceeded(Exception):
    def __init__(self, used: int, quota: int, incoming: int) -> None:
        super().__init__(f"This would go over your {quota // (1024**3)} GB space ({used // (1024**2)} MB used).")
        self.used, self.quota, self.incoming = used, quota, incoming


def _enforcement_file() -> str:
    return os.path.join(config.DATA_DIR, "quota_enforcement.json")


def enforcement(home: str) -> dict[str, Any] | None:
    """How the last limit set on a home folder is held: by the filesystem, or on uploads only."""
    return (read_json(_enforcement_file(), {}) or {}).get(home)


def homes_root() -> str:
    return os.path.join(getattr(config, "POOL_PATH", "/mnt/user"), "homes")


def home_of(username: str) -> str:
    from backend.users_db import get_user_by_username

    user = get_user_by_username(username) or {}
    return user.get("home_directory") or os.path.join(homes_root(), username.lower())


def quota_of(username: str) -> int:
    from backend.users_db import get_user_by_username

    return int((get_user_by_username(username) or {}).get("storage_quota_bytes") or 0)


def _btrfs(args: list[str]) -> bool:
    try:
        return subprocess.run(["btrfs", *args], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_home(username: str, quota_bytes: int = 0) -> dict[str, Any]:
    """Creates the person's folder (a Btrfs subvolume when the pool is Btrfs) and applies the quota."""
    home = home_of(username)
    created = False
    if not os.path.isdir(home):
        os.makedirs(os.path.dirname(home), exist_ok=True)
        created = _btrfs(["subvolume", "create", home]) or False
        if not created:  # a ZFS dataset of its own when the homes folder is one (FEAT-10)
            created = bool(fs_quota.zfs_child_dataset(os.path.dirname(home), os.path.basename(home)))
        if not created:
            os.makedirs(home, exist_ok=True)
        try:
            os.chmod(home, 0o770)
        except OSError:
            logger.debug("user_spaces: chmod failed", exc_info=True)
    held = apply_fs_quota(home, quota_bytes) if quota_bytes else False
    return {"home": home, "subvolume": created, "fs_quota": held}


def apply_fs_quota(home: str, quota_bytes: int) -> bool:
    """The filesystem's own limit on the home (btrfs, ZFS or XFS); True when it holds there."""
    result = fs_quota.apply(home, quota_bytes)
    _record(home, {**result, "quota_bytes": int(quota_bytes or 0)})
    if not result["enforced"] and quota_bytes:
        logger.info("[Spaces] %s: limit checked on uploads only (%s)", home, result["reason"])
    return bool(result["enforced"])


@json_locked(lambda *a, **k: _enforcement_file())
def _record(home: str, result: dict[str, Any]) -> None:
    saved = read_json(_enforcement_file(), {}) or {}
    saved[home] = result
    atomic_write_json(_enforcement_file(), saved)


def set_quota(username: str, quota_bytes: int) -> bool:
    """A changed limit reaches the filesystem too, not only the account (FEAT-10)."""
    home = home_of(username)
    if not os.path.isdir(home):
        return bool(ensure_home(username, quota_bytes)["fs_quota"])
    return apply_fs_quota(home, quota_bytes)


def usage(username: str, fresh: bool = False) -> int:
    """Bytes used in the person's home (cached for a minute)."""
    home = home_of(username)
    now = time.time()
    with _lock:
        hit = _usage_cache.get(home)
        if hit and not fresh and now - hit[0] < _USAGE_TTL:
            return hit[1]
    total = 0
    for root, _dirs, files in os.walk(home):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    with _lock:
        _usage_cache[home] = (now, total)
    return total


def check_upload(username: str, target_path: str, incoming: int) -> int | None:
    """Raises QuotaExceeded when an upload into the person's own home would exceed the quota.
    Returns the bytes still allowed (None when no quota applies to this target)."""
    quota = quota_of(username)
    if not quota or not username:
        return None
    home = os.path.realpath(home_of(username))
    real = os.path.realpath(target_path)
    if not (real == home or real.startswith(home.rstrip(os.sep) + os.sep)):
        return None
    used = usage(username, fresh=True)
    if used + max(0, incoming) > quota:
        raise QuotaExceeded(used, quota, incoming)
    return quota - used


def summary(username: str) -> dict[str, Any]:
    quota = quota_of(username)
    home = home_of(username)
    return {"home": home, "used_bytes": usage(username), "quota_bytes": quota, "enforcement": enforcement(home)}
