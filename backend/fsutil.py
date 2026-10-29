"""
Filesystem helpers: crash-safe JSON persistence and path containment checks.
"""

import contextlib
import functools
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

_JSON_CACHE: dict[str, tuple[float | None, Any, float]] = {}  # mtime None: the file was missing

# Settings files the app writes itself: atomic_write_json refreshes the cached copy, so hot
# loops only need to look at the file now and then for edits made outside the app. On hosts
# where the data folder is a FUSE mount (Unraid's /mnt/user) every look blocks (PERF-5).
SETTINGS_RECHECK_SECS = 30.0


def clear_json_cache() -> None:
    _JSON_CACHE.clear()


def atomic_write_json(path: str, data: Any, indent: int | None = None) -> None:
    """Write JSON to `path` atomically (temp file + fsync + os.replace).

    A crash or power loss mid-write leaves either the old file or the new
    file intact — never a truncated/corrupt one. The file is readable by its
    owner only (0600), which suits settings that hold secrets.
    """
    if os.path.abspath(path) in _UNREADABLE and os.path.exists(path):
        try:
            with open(path) as f:
                f.read(1)
            _UNREADABLE.discard(os.path.abspath(path))
        except OSError as e:
            # its settings are still in there: never replace a file just because it couldn't be read
            raise OSError(f"{os.path.basename(path)} could not be read, so it was not overwritten: {e}") from e
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


_JSON_LOCKS: dict[str, threading.RLock] = {}
_JSON_LOCKS_GUARD = threading.Lock()


@contextlib.contextmanager
def locked_json(path: str):
    """Hold this file's lock for a read-modify-write, so two writers can't undo each other (ARC-2).

    Re-entrant: a locked function may call another that locks the same file."""
    key = os.path.abspath(path)
    with _JSON_LOCKS_GUARD:
        lock = _JSON_LOCKS.setdefault(key, threading.RLock())
    with lock:
        yield


def json_locked(path_of):
    """Decorator: holds the lock of the file `path_of(*args, **kwargs)` names for the whole call.
    `path_of` runs at call time, so a path a test or a setting changes is honoured."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with locked_json(path_of(*args, **kwargs)):
                return fn(*args, **kwargs)

        return wrapper

    return deco


def atomic_write_text(path: str, text: str, mode: int = 0o644) -> None:
    """Write text to `path` atomically (temp file + fsync + os.replace): a crash mid-write leaves
    the old file or the new one, never half of it (REL-22)."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def read_json(path: str, default: Any = None) -> Any:
    """Read JSON from `path`, returning `default` if it is missing.

    A file that exists but isn't valid JSON is renamed to `<name>.corrupt-<time>` first, so the
    next save can't overwrite what might still be recovered from it (REL-2), and the newest good
    copy from the data snapshots is put back when there is one (REL-21).

    A file that exists but can't be opened (permissions, an I/O error) is not "corrupt" and is
    not moved: it is reported, `default` is returned, and atomic_write_json refuses to replace
    it until it can be read again, so a passing problem never costs the settings (REL-21)."""
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return default
    except OSError as e:
        _mark_unreadable(path, e)
        return default
    except (json.JSONDecodeError, UnicodeDecodeError):
        quarantine_corrupt(path)
        if _restore(path):
            try:
                with open(path) as f:
                    return json.load(f)
            except (OSError, ValueError):
                return default
        return default
    _UNREADABLE.discard(os.path.abspath(path))
    return data


# Called with (path) after a damaged file was set aside: put a good copy back, True if done.
# backend.services.data_health adds the snapshot restore at start (fsutil can't import it).
RESTORERS: list = []
# Called with (path, error) when a settings file exists but can't be opened.
UNREADABLE_LISTENERS: list = []
_UNREADABLE: set[str] = set()


def _restore(path: str) -> bool:
    for restorer in list(RESTORERS):
        try:
            if restorer(path):
                return True
        except Exception:
            logger.warning(f"[fsutil] could not restore {os.path.basename(path)}", exc_info=True)
    return False


def _mark_unreadable(path: str, error: OSError) -> None:
    key = os.path.abspath(path)
    first = key not in _UNREADABLE
    _UNREADABLE.add(key)
    if not first:
        return
    logger.error(f"[fsutil] {os.path.basename(path)} exists but could not be opened: {error}")
    for listener in list(UNREADABLE_LISTENERS):
        try:
            listener(path, str(error))
        except Exception:
            logger.debug("fsutil: could not record the unreadable-file event", exc_info=True)


# Called with (path, dest) when a damaged settings file is set aside. backend.state adds the
# event; fsutil sits below it and must not import it (ARC-6).
CORRUPT_LISTENERS: list = []


def quarantine_corrupt(path: str) -> str | None:
    """Moves an unreadable settings file aside and records it; returns the new name."""
    dest = f"{path}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        os.replace(path, dest)
    except OSError:
        logger.warning(f"[fsutil] {path} is unreadable and could not be moved aside", exc_info=True)
        return None
    logger.error(f"[fsutil] {os.path.basename(path)} was not valid JSON; kept as {os.path.basename(dest)}")
    for listener in list(CORRUPT_LISTENERS):
        try:
            listener(path, dest)
        except Exception:
            logger.debug("fsutil: could not record the damaged-file event", exc_info=True)
    return dest


def read_json_cached(path: str, default: Any = None, max_age: float = 3.0) -> Any:
    """Read JSON from `path` with in-memory caching to eliminate redundant disk I/O on hot loops."""
    try:
        now = time.time()
        cached = _JSON_CACHE.get(path)
        if cached:
            cached_mtime, cached_data, checked_at = cached
            if (now - checked_at) < max_age:
                # a file that was missing stays missing until the next check (PERF-22)
                return default if cached_mtime is None else cached_data
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
    except FileNotFoundError:
        # optional settings files are often absent: remember it, instead of a stat on every
        # call (FUSE on Unraid; PERF-22)
        _JSON_CACHE[path] = (None, None, time.time())
        return default
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


def safe_serve_root(path: str, pool_path: str) -> str | None:
    """The canonical folder WebDAV/SFTP may serve as an account's root, or None (SEC-20).

    It must lie inside the browse roots, must not be an app folder, and must not contain
    one: rclone's excludes for the app folders are written for the pool root only, so the
    pool root itself is the one root allowed to contain them."""
    import backend.config as config

    if not path:
        return None
    roots = [*(getattr(config, "ALLOWED_BROWSE_ROOTS", None) or []), *([pool_path] if pool_path else [])]
    real = resolve_within(path, roots)
    if real is None:
        return None
    pool_real = os.path.realpath(pool_path) if pool_path else ""
    if real != pool_real and any(_inside(d, real) for d in protected_dirs()):
        return None
    return real


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
        if real == real_root:
            return real_root
        # a separate prefix check on the resolved path, the shape code scanners recognise as a guard
        if not real.startswith(real_root.rstrip(os.sep) + os.sep):
            continue
        if any(_inside(real, d) and not _inside(real_root, d) for d in protected_dirs()):
            return None
        return real
    return None


def single_name(name: str) -> str:
    """`name` when it is one file or folder name; ValueError for a /, '.', '..' or an empty name,
    which would put a snapshot or subvolume somewhere other than its own folder."""
    if not name or "/" in name or "\x00" in name or name in (".", ".."):
        raise ValueError("Use a single name, without / and not . or ..")
    return name


def child_path(parent: str, name: str) -> str:
    """parent/name for a single name (see single_name); never a path outside `parent`."""
    single_name(name)
    base = os.path.normpath(parent)
    path = os.path.normpath(os.path.join(base, name))
    if not path.startswith(base.rstrip(os.sep) + os.sep):
        raise ValueError("Use a single name, without / and not . or ..")
    return path


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
