"""
Filesystem helpers: crash-safe JSON persistence and path containment checks.
"""
import os
import json
import tempfile
from typing import Any, Iterable, Optional


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
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_json(path: str, default: Any = None) -> Any:
    """Read JSON from `path`, returning `default` if missing or unreadable."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def resolve_within(path: str, roots: Iterable[str]) -> Optional[str]:
    """Return the canonical (symlink-resolved) path if it lies inside one of
    `roots`, otherwise None. Defeats `..` segments and symlink escapes."""
    if not path:
        return None
    real = os.path.realpath(path)
    for root in roots:
        real_root = os.path.realpath(root)
        if real == real_root or real.startswith(real_root.rstrip(os.sep) + os.sep):
            return real
    return None


def root_for(path: str, roots: Iterable[str]) -> Optional[str]:
    """Return the canonical root that contains `path` (already canonical)."""
    for root in roots:
        real_root = os.path.realpath(root)
        if path == real_root or path.startswith(real_root.rstrip(os.sep) + os.sep):
            return real_root
    return None
