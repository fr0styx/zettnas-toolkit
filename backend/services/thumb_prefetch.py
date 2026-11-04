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
_workers: list[threading.Thread] = []
WORKERS = 2  # a folder's queue is worked by two threads; each yields to thumbnails on screen


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


def waiting() -> int:
    """How many thumbnails the folder queue still has to make (for the Jobs centre)."""
    with _lock:
        return len(_queue)


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
        return thumbs.get(path, background=True) is not None
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
    with _lock:
        _workers[:] = [w for w in _workers if w.is_alive()]
        while len(_workers) < WORKERS:
            w = threading.Thread(target=drain, name="thumb-prefetch", daemon=True)
            _workers.append(w)
            w.start()


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
        self.job_id: str | None = None  # this pass in the Jobs centre, once it makes something (NJOB-1)
        self.last_id = 0

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

    def _detail(self) -> str:
        return f"{self.made} made, {self.deferred} waiting for sleeping disks"

    def _report(self) -> None:
        """Shows the pass in the Jobs centre once it has made a thumbnail; a pass that only checks
        (everything already there) stays out of it."""
        from backend.services.jobs import job_manager

        if self.job_id is None and self.made:
            conn = self.engine._get_conn()
            try:
                row = conn.execute(
                    "SELECT MAX(file_id) FROM indexed_files WHERE modality IN ('image', 'video')"
                ).fetchone()
            finally:
                conn.close()
            self.last_id = int((row or [0])[0] or 0)
            job = job_manager.register("thumbnails", "Making photo and video thumbnails", title_id="jobs.t.thumbs")
            self.job_id = job.id
        if self.job_id is not None:
            percent = min(99.0, 100.0 * self.cursor / self.last_id) if self.last_id else None
            job_manager.update(self.job_id, detail=self._detail(), percent=percent)

    def _paused(self) -> str:
        """A busy NAS stops the pass for a while; its Jobs row stays and says why (NJOB-1)."""
        if self.job_id is not None:
            from backend.services.jobs import job_manager

            job_manager.update(self.job_id, detail=f"{self._detail()}, paused while the NAS is busy")
        return "busy"

    def _finish_pass(self) -> str:
        logger.info(
            "[Thumbnails] Background pass done: %d made, %d left for when their disk is awake",
            self.made,
            self.deferred,
        )
        if self.job_id is not None:
            from backend.services.jobs import job_manager

            job_manager.update(self.job_id, detail=self._detail())
            job_manager.finish(self.job_id)
            self.job_id = None
        self.cursor, self.made, self.deferred = 0, 0, 0
        return "done"

    def step(self) -> str:
        """One batch: 'busy' (try again later), 'more' or 'done' (a whole pass finished)."""
        if not self.idle():
            return self._paused()
        rows = self.rows()
        if not rows:
            return self._finish_pass()
        for i, (file_id, path, dev) in enumerate(rows):
            if i and i % IDLE_CHECK_EVERY == 0 and not self.idle():
                return self._paused()
            self.cursor = int(file_id)
            if _encrypted(path):
                continue
            if self.asleep(dev or ""):
                self.deferred += 1
                continue
            if make(path):
                self.made += 1
                self._report()  # in the Jobs centre from the first thumbnail, not after a whole batch
        self._report()
        return "more"

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        while True:
            try:
                state = self.step()
            except (OSError, sqlite3.Error):
                logger.warning("[Thumbnails] Background pass paused", exc_info=True)
                state = "busy"
            sleep(PASS_PAUSE_S if state == "done" else BUSY_PAUSE_S if state == "busy" else STEP_PAUSE_S)


def folder_jobs() -> list[Any]:
    """A folder's waiting thumbnails, for the Jobs centre (NJOB-1)."""
    from backend.services.jobs import Job

    left = waiting()
    if not left:
        return []
    return [
        Job(
            id="thumbs:folder",
            kind="thumbnails",
            title="Making thumbnails for an opened folder",
            title_id="jobs.t.thumbs_folder",
            detail=f"{left} waiting",
        )
    ]


def _register_jobs_source() -> None:
    from backend.services import jobs

    jobs.SOURCES["thumbs"] = (folder_jobs, None)


_register_jobs_source()
