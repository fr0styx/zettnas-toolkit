"""
Filesystem helpers: crash-safe JSON persistence and path containment checks.
"""

import glob
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from collections.abc import Iterable
from typing import Any

_JSON_CACHE: dict[str, tuple[float, Any, float]] = {}


def atomic_write_json(path: str, data: Any, indent: int | None = None) -> None:
    """Write JSON to `path` atomically (temp file + fsync + os.replace).

    A crash or power loss mid-write leaves either the old file or the new
    file intact — never a truncated/corrupt one. The file is readable by its
    owner only (0600), which suits settings that hold secrets.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        now = time.time()
        _JSON_CACHE[path] = (now, data, now)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path: str, default: Any = None) -> Any:
    """Read JSON from `path`, returning `default` if missing or unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def read_json_cached(path: str, default: Any = None, max_age: float = 3.0) -> Any:
    """Read JSON from `path` with in-memory caching to eliminate redundant disk I/O on hot loops."""
    try:
        now = time.time()
        cached = _JSON_CACHE.get(path)
        if cached:
            cached_mtime, cached_data, checked_at = cached
            if (now - checked_at) < max_age:
                return cached_data
            stat = os.stat(path)
            if stat.st_mtime == cached_mtime:
                _JSON_CACHE[path] = (cached_mtime, cached_data, now)
                return cached_data
            data = read_json(path, default)
            _JSON_CACHE[path] = (stat.st_mtime, data, now)
            return data
        stat = os.stat(path)
        data = read_json(path, default)
        _JSON_CACHE[path] = (stat.st_mtime, data, now)
        return data
    except (OSError, json.JSONDecodeError):
        return default


# --- The app's own folders (SEC-3) -------------------------------------------------------
# The data folder holds users.db, secret.key and backup credentials. On many hosts it is also
# visible inside a browse root (Unraid: /mnt/user/appdata/zettnas-toolkit/data), under another
# path than DATA_DIR. A marker file with a random id finds those aliases without guessing.

logger = logging.getLogger("ZettNAS")

DATA_MARKER = ".zettnas-data-id"
_PROTECTED: list[str] | None = None
_PROTECTED_LOCK = threading.Lock()


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def _data_marker(data_dir: str) -> str:
    marker = os.path.join(data_dir, DATA_MARKER)
    try:
        with open(marker, encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            return value
    except OSError:
        logger.debug("fsutil: no data marker yet", exc_info=True)
    value = secrets.token_hex(16)
    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(value)
        return value
    except OSError:
        return ""


def _discover_protected() -> list[str]:
    import backend.config as config

    data_dir = getattr(config, "DATA_DIR", "") or ""
    if not data_dir:
        return []
    data_real = os.path.realpath(data_dir)
    found = {data_real}
    marker_id = _data_marker(data_real)
    roots = [os.path.realpath(r) for r in (getattr(config, "ALLOWED_BROWSE_ROOTS", None) or [])]
    candidates = [c for c in os.environ.get("ZETTNAS_DATA_HOST_PATHS", "").split(os.pathsep) if c]
    for root in roots:
        # appdata folders sit on fast storage; the share roots themselves are never listed,
        # so finding the alias doesn't wake sleeping disks
        candidates += glob.glob(os.path.join(root, "appdata", "*", "data"))
        candidates += glob.glob(os.path.join(root, "appdata", "*", "*", "data"))
        if os.path.basename(root) == "appdata":
            candidates += glob.glob(os.path.join(root, "*", "data"))
    if marker_id:
        for cand in candidates:
            try:
                with open(os.path.join(cand, DATA_MARKER), encoding="utf-8") as f:
                    if f.read().strip() == marker_id:
                        found.add(os.path.realpath(cand))
            except OSError:
                continue
    # the install folder next to the data folder (compose file, .env with secrets)
    for folder in list(found):
        parent = os.path.dirname(folder)
        if parent in ("", os.sep) or parent in roots or os.path.basename(parent) == "appdata":
            continue
        if any(os.path.exists(os.path.join(parent, n)) for n in ("docker-compose.yml", "compose.yaml", ".env")):
            found.add(parent)
    return sorted(found)


def protected_dirs() -> list[str]:
    """Canonical folders no file feature may reach: the data folder, its aliases, the install folder."""
    global _PROTECTED
    if _PROTECTED is None:
        with _PROTECTED_LOCK:
            if _PROTECTED is None:
                _PROTECTED = _discover_protected()
    return _PROTECTED


def reset_protected_dirs() -> None:
    """Forget the discovered folders (settings or tests changed DATA_DIR or the browse roots)."""
    global _PROTECTED
    with _PROTECTED_LOCK:
        _PROTECTED = None


def is_protected(path: str) -> bool:
    """True if `path` (canonical, as from resolve_within or a walk under one) is an app folder.
    String comparison only: cheap enough for every entry of a folder walk."""
    if not path:
        return False
    p = path.rstrip(os.sep) or os.sep
    return any(_inside(p, d) for d in protected_dirs())


def prune_protected(dirpath: str, dirnames: list[str]) -> None:
    """For os.walk: drop app folders from `dirnames` in place so the walk never enters them."""
    dirnames[:] = [n for n in dirnames if not is_protected(os.path.join(dirpath, n))]


def protected_rclone_excludes(base: str) -> list[str]:
    """rclone filter flags hiding the app folders that lie under `base` (an rclone serve root)."""
    base_real = os.path.realpath(base) if base else ""
    flags: list[str] = []
    for d in protected_dirs():
        if base_real and _inside(d, base_real) and d != base_real:
            rel = os.path.relpath(d, base_real).replace(os.sep, "/")
            flags += ["--exclude", f"/{rel}/**", "--exclude", f"/{rel}"]
    return flags


def resolve_within(path: str, roots: Iterable[str] | str) -> str | None:
    """Return the canonical (symlink-resolved) path if it lies inside one of
    `roots`, otherwise None. Defeats `..` segments and symlink escapes.

    The app's own folders are refused unless the caller passed a root inside them (SEC-3)."""
    if not path or not roots:
        return None
    if isinstance(roots, (str, bytes)):
        roots = [roots]
    real = os.path.realpath(path)
    for root in roots:
        real_root = os.path.realpath(root)
        if real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep):
            if any(_inside(real, d) and not _inside(real_root, d) for d in protected_dirs()):
                return None
            return real
    return None


def root_for(path: str, roots: Iterable[str] | str) -> str | None:
    """Return the canonical root that contains `path` (already canonical)."""
    if not path or not roots:
        return None
    if isinstance(roots, (str, bytes)):
        roots = [roots]
    for root in roots:
        real_root = os.path.realpath(root)
        if path == real_root or path.startswith(real_root.rstrip(os.sep) + os.sep):
            return real_root
    return None
