"""Thumbnails made ahead of time (NPERF-8), so a folder of photos and videos shows its pictures at once.

Two ways in, each one file at a time on a background thread, into the cache the explorer reads
(thumbs.py):
- queue_folder(): opening a folder queues its photos and videos, the newest folder first.
- Backfill: while the system is idle it walks the AI index's photos and videos and makes the
  thumbnails that are missing, only for files whose disk is already awake (it never wakes one),
  so the library fills in over time and a folder nobody has opened yet is ready too.
"""

import collections
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.services import thumbs

logger = logging.getLogger("zettnas.thumb_prefetch")

MAX_QUEUE = 5000
BATCH = 200
IDLE_CHECK_EVERY = 20
PASS_PAUSE_S = 6 * 3600
BUSY_PAUSE_S = 60.0
STEP_PAUSE_S = 0.05

_lock = threading.Lock()
_queue: collections.deque[str] = collections.deque()
_queued: set[str] = set()
_worker: threading.Thread | None = None


def _encrypted(path: str) -> bool:
    from backend.fsutil import ENCRYPTED_ROOT

    return os.path.realpath(path).startswith(ENCRYPTED_ROOT + os.sep)


def folder_media(folder: str) -> list[str]:
    """The photos and videos directly in `folder`, by name; none in an open encrypted folder,
    whose previews are never cached (NSEC-3)."""
    if _encrypted(folder):
        return []
    try:
        with os.scandir(folder) as entries:
            names = sorted(
                e.name
                for e in entries
                if not e.name.startswith(".") and thumbs.kind(e.name) and e.is_file(follow_symlinks=False)
            )
    except OSError:
        logger.debug("Could not list %s", folder, exc_info=True)
        return []
    return [os.path.join(folder, n) for n in names]


def queue_folder(folder: str) -> int:
    """Queues the folder's photos and videos ahead of what was queued before; returns how many."""
    paths = folder_media(folder)
    with _lock:
        fresh = [p for p in paths if p not in _queued][:MAX_QUEUE]
        for p in reversed(fresh):
            _queue.appendleft(p)
            _queued.add(p)
        while len(_queue) > MAX_QUEUE:
            _queued.discard(_queue.pop())
    if fresh:
        _ensure_worker()
    return len(fresh)


def _next() -> str | None:
    with _lock:
        if not _queue:
            return None
        path = _queue.popleft()
        _queued.discard(path)
        return path


def make(path: str) -> bool:
    """Makes the thumbnail when it is missing; True when one was made."""
    try:
        if thumbs.cached(path):
            return False
        return thumbs.get(path) is not None
    except OSError:
        logger.debug("No thumbnail for %s", path, exc_info=True)
        return False


def drain() -> int:
    """Works through the folder queue; returns how many thumbnails it made."""
    made = 0
    while (path := _next()) is not None:
        made += make(path)
    return made


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=drain, name="thumb-prefetch", daemon=True)
        _worker.start()


def _disk_asleep(dev: str) -> bool:
    from backend.services import rag_standby

    return rag_standby.is_backing_disk_in_standby(dev)


class Backfill:
    """Walks the indexed photos and videos in file_id order and fills in missing thumbnails."""

    def __init__(self, engine: Any, idle: Callable[[], bool], asleep: Callable[[str], bool] = _disk_asleep):
        self.engine = engine
        self.idle = idle
        self.asleep = asleep
        self.cursor = 0
        self.made = 0
        self.deferred = 0

    def rows(self) -> list[tuple[int, str, str]]:
        conn = self.engine._get_conn()
        try:
            return conn.execute(
                """SELECT file_id, canonical_path, backing_dev FROM indexed_files
                   WHERE modality IN ('image', 'video') AND parse_status = 'ok' AND file_id > ?
                   ORDER BY file_id LIMIT ?""",
                (self.cursor, BATCH),
            ).fetchall()
        finally:
            conn.close()

    def _finish_pass(self) -> str:
        logger.info(
            "[Thumbnails] Background pass done: %d made, %d left for when their disk is awake",
            self.made,
            self.deferred,
        )
        self.cursor, self.made, self.deferred = 0, 0, 0
        return "done"

    def step(self) -> str:
        """One batch: 'busy' (try again later), 'more' or 'done' (a whole pass finished)."""
        if not self.idle():
            return "busy"
        rows = self.rows()
        if not rows:
            return self._finish_pass()
        for i, (file_id, path, dev) in enumerate(rows):
            if i and i % IDLE_CHECK_EVERY == 0 and not self.idle():
                return "busy"
            self.cursor = int(file_id)
            if _encrypted(path):
                continue
            if self.asleep(dev or ""):
                self.deferred += 1
                continue
            self.made += make(path)
        return "more"

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        while True:
            try:
                state = self.step()
            except (OSError, sqlite3.Error):
                logger.warning("[Thumbnails] Background pass paused", exc_info=True)
                state = "busy"
            sleep(PASS_PAUSE_S if state == "done" else BUSY_PAUSE_S if state == "busy" else STEP_PAUSE_S)
