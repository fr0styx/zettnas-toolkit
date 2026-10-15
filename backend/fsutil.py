"""
Filesystem helpers: crash-safe JSON persistence and path containment checks.
"""

import json
import os
import tempfile
import time
from collections.abc import Iterable
from typing import Any

_JSON_CACHE: dict[str, tuple[float, Any, float]] = {}


def atomic_write_json(path: str, data: Any) -> None:
    """Write JSON to `path` atomically (temp file + fsync + os.replace).

    A crash or power loss mid-write leaves either the old file or the new
    file intact — never a truncated/corrupt one.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
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


def resolve_within(path: str, roots: Iterable[str] | str) -> str | None:
    """Return the canonical (symlink-resolved) path if it lies inside one of
    `roots`, otherwise None. Defeats `..` segments and symlink escapes."""
    if not path or not roots:
        return None
    if isinstance(roots, (str, bytes)):
        roots = [roots]
    real = os.path.realpath(path)
    for root in roots:
        real_root = os.path.realpath(root)
        if real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep):
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
