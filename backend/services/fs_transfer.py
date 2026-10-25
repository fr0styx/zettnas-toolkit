"""
ZettNAS Toolkit - Resilient Filesystem Transfer & Directory Merge Engine
Handles recursive directory merging, unified collision resolution (Merge, Overwrite, Skip, Keep Both),
and cross-filesystem EXDEV (Invalid cross-device link) boundary fallbacks.
"""

import asyncio
import collections
import errno
import os
import shutil
import tarfile
import threading
import time
import uuid
import zipfile
from collections.abc import Callable
from enum import Enum, StrEnum
from typing import Any, Optional

from backend.config import logger
from backend.fsutil import is_protected, prune_protected


class CollisionPolicy(StrEnum):
    MERGE = "merge"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    KEEP_BOTH = "keep_both"


def _generate_unique_target(dst_path: str) -> str:
    """Generate a non-colliding path by appending ' (1)', ' (2)', etc. before the extension."""
    if not os.path.lexists(dst_path):
        return dst_path

    parent = os.path.dirname(dst_path)
    base = os.path.basename(dst_path)

    if os.path.isdir(dst_path):
        stem, ext = base, ""
    else:
        stem, ext = os.path.splitext(base)

    counter = 1
    while True:
        candidate_name = f"{stem} ({counter}){ext}"
        candidate_path = os.path.join(parent, candidate_name)
        if not os.path.lexists(candidate_path):
            return candidate_path
        counter += 1


def check_transfer_conflicts(sources: list[str], destination_dir: str) -> dict[str, Any]:
    """Pre-flight check: inspect whether any source items conflict with existing items in destination_dir."""
    conflicts = []

    for src in sources:
        if not os.path.lexists(src):
            continue

        item_name = os.path.basename(src.rstrip("/\\"))
        dst_target = os.path.join(destination_dir, item_name)

        if os.path.lexists(dst_target):
            is_dir = os.path.isdir(src) and os.path.isdir(dst_target)
            src_stat = os.stat(src) if os.path.exists(src) else None
            dst_stat = os.stat(dst_target) if os.path.exists(dst_target) else None

            conflicts.append(
                {
                    "source": src,
                    "destination": dst_target,
                    "name": item_name,
                    "is_dir": is_dir,
                    "source_size": src_stat.st_size if src_stat and not is_dir else 0,
                    "dest_size": dst_stat.st_size if dst_stat and not is_dir else 0,
                    "source_mtime": src_stat.st_mtime if src_stat else 0.0,
                    "dest_mtime": dst_stat.st_mtime if dst_stat else 0.0,
                }
            )

    return {
        "has_conflict": len(conflicts) > 0,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


class TransferCancelled(Exception):
    """Raised inside a transfer when the user cancels it (deliberately not an OSError)."""


class TransferProgress:
    """Progress hooks for a transfer; the base class does nothing.

    The background worker subclasses it to count bytes and files, pause and cancel.
    """

    def checkpoint(self) -> None:
        """Called between files and copy chunks: blocks while paused, raises TransferCancelled."""

    def current(self, path: str) -> None:
        pass

    def add_bytes(self, n: int) -> None:
        pass

    def file_done(self) -> None:
        pass

    def done_totals(self, files: int, nbytes: int) -> None:
        """Counts files and bytes as done without copying them (skipped, or renamed in one step)."""

    def skip_tree(self, path: str) -> None:
        """Counts everything under `path` as done."""


_NO_PROGRESS = TransferProgress()
_COPY_STEP = 16 * 1024 * 1024  # bytes per kernel copy call: keeps pause, cancel and progress responsive


def tree_totals(path: str) -> tuple[int, int]:
    """(files, bytes) under a path, without following symlinks."""
    if os.path.islink(path) or not os.path.isdir(path):
        try:
            return 1, (0 if os.path.islink(path) else os.path.getsize(path))
        except OSError:
            return 1, 0
    files = size = 0
    for root, _dirs, names in os.walk(path):
        prune_protected(root, _dirs)
        for name in names:
            files += 1
            full = os.path.join(root, name)
            try:
                if not os.path.islink(full):
                    size += os.path.getsize(full)
            except OSError as err:
                logger.debug(f"[FS Transfer] Cannot size {full}: {err}")
    return files, size


def _part_path(dst: str) -> str:
    """Where a file is written before it is renamed into place: hidden, next to the target."""
    return os.path.join(os.path.dirname(dst), f".{os.path.basename(dst)}.zettnas-part")


def _stream_copy(src: str, dst: str, progress: TransferProgress) -> None:
    """Copies file data with the kernel's copy (reflinks on btrfs/XFS), falling back to read/write."""
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        in_fd, out_fd = fsrc.fileno(), fdst.fileno()
        use_kernel = hasattr(os, "copy_file_range")
        while True:
            progress.checkpoint()
            if use_kernel:
                try:
                    n = os.copy_file_range(in_fd, out_fd, _COPY_STEP)
                except OSError:
                    use_kernel = False  # FUSE/rclone mounts and some kernels: copy by hand
                    continue
            else:
                buf = fsrc.read(1024 * 1024)
                n = len(buf)
                if n:
                    fdst.write(buf)
            if not n:
                break
            progress.add_bytes(n)


def _copy_file_resilient(src: str, dst: str, progress: TransferProgress | None = None) -> None:
    """Copies a file with its metadata. With progress, the data goes to a hidden part file that
    replaces `dst` only when complete, so a cancel or failure never leaves a broken file."""
    if progress is None:
        try:
            if os.path.islink(src):
                shutil.copy2(src, dst, follow_symlinks=False)
            else:
                shutil.copy2(src, dst)
        except OSError:
            shutil.copyfile(src, dst)
        return
    if os.path.islink(src):
        if os.path.lexists(dst) and not os.path.isdir(dst):
            os.unlink(dst)
        shutil.copy2(src, dst, follow_symlinks=False)
        return
    part = _part_path(dst)
    try:
        _stream_copy(src, part, progress)
        try:
            shutil.copystat(src, part)
        except OSError as err:  # FUSE/cloud remotes may not keep times or modes
            logger.debug(f"[FS Transfer] Times/mode not kept for {dst}: {err}")
        os.replace(part, dst)
    except BaseException:
        try:
            os.unlink(part)
        except FileNotFoundError:
            logger.debug(f"[FS Transfer] No part file to remove for {dst}")
        except OSError as err:
            logger.warning(f"[FS Transfer] Could not remove unfinished {part}: {err}")
        raise


def _move_file_resilient(src: str, dst: str, progress: TransferProgress | None = None) -> None:
    """Moves a file: a rename on the same filesystem, else copy then delete the original."""
    size = 0
    if progress is not None:
        try:
            size = 0 if os.path.islink(src) else os.path.getsize(src)
        except OSError as err:
            logger.debug(f"[FS Transfer] Cannot size {src}: {err}")
    try:
        os.replace(src, dst)
        if progress is not None:
            progress.add_bytes(size)
        return
    except OSError as err:
        logger.debug(f"[FS Transfer] Rename {src} failed ({err}); copying instead")
    _copy_file_resilient(src, dst, progress)
    try:
        os.unlink(src)
    except OSError as err:
        logger.warning(f"[FS Transfer] Moved {src} but could not remove the original: {err}")


def _transfer_single_file(
    src: str,
    dst: str,
    action: str = "copy",
    policy: CollisionPolicy = CollisionPolicy.OVERWRITE,
    progress: TransferProgress | None = None,
) -> str:
    """
    Transfers a single file respecting collision policy.
    Returns: 'transferred', 'skipped', or 'renamed'.
    """
    prog = progress or _NO_PROGRESS
    prog.checkpoint()
    prog.current(src)
    final_dst = dst
    if os.path.lexists(dst):
        if policy == CollisionPolicy.SKIP:
            prog.skip_tree(src)
            return "skipped"
        elif policy == CollisionPolicy.KEEP_BOTH:
            final_dst = _generate_unique_target(dst)
        elif policy in (CollisionPolicy.OVERWRITE, CollisionPolicy.MERGE):
            final_dst = dst

    os.makedirs(os.path.dirname(final_dst), exist_ok=True)

    if action == "move":
        _move_file_resilient(src, final_dst, progress)
    else:
        _copy_file_resilient(src, final_dst, progress)
    prog.file_done()

    return "renamed" if final_dst != dst else "transferred"


def merge_directory_tree(
    src_dir: str,
    dst_dir: str,
    action: str = "copy",
    policy: CollisionPolicy = CollisionPolicy.MERGE,
    stats: dict[str, Any] | None = None,
    progress: TransferProgress | None = None,
) -> dict[str, Any]:
    """
    Recursively merges src_dir into dst_dir:
    - If policy == MERGE: creates subdirectories and transfers non-conflicting child items.
    - If policy == OVERWRITE: replaces existing directory entirely.
    - If policy == SKIP: skips entire directory if destination exists.
    - If policy == KEEP_BOTH: renames target directory e.g. dst_dir (1).
    A move only removes source folders that end up empty, so skipped files stay where they were.
    """
    if stats is None:
        stats = {"transferred": 0, "skipped": 0, "merged_dirs": 0}
    prog = progress or _NO_PROGRESS
    prog.checkpoint()

    dst_exists = os.path.lexists(dst_dir)

    if dst_exists:
        if policy == CollisionPolicy.SKIP:
            stats["skipped"] += 1
            prog.skip_tree(src_dir)
            return stats
        elif policy == CollisionPolicy.KEEP_BOTH:
            dst_dir = _generate_unique_target(dst_dir)
            dst_exists = False
        elif policy == CollisionPolicy.OVERWRITE:
            if os.path.isdir(dst_dir) and not os.path.islink(dst_dir):
                shutil.rmtree(dst_dir)
            else:
                os.unlink(dst_dir)
            dst_exists = False

    # Destination directory now either does not exist or we are performing MERGE
    if not dst_exists:
        if action == "move":
            # Same filesystem: one rename moves the whole folder
            totals = tree_totals(src_dir) if progress is not None else (0, 0)
            try:
                os.rename(src_dir, dst_dir)
                stats["transferred"] += 1
                prog.current(src_dir)
                prog.done_totals(*totals)
                return stats
            except OSError:
                # Cross-device move or FUSE/rclone remote: continue with recursive leaf transfer
                pass
        os.makedirs(dst_dir, exist_ok=True)
    else:
        stats["merged_dirs"] += 1

    try:
        entries = [e for e in os.scandir(src_dir) if not is_protected(e.path)]
    except OSError as err:
        logger.error(f"[FS Transfer] Cannot scan directory {src_dir}: {err}")
        return stats

    for entry in entries:
        src_child = entry.path
        dst_child = os.path.join(dst_dir, entry.name)

        if entry.is_dir(follow_symlinks=False):
            # Recurse into child directory
            merge_directory_tree(
                src_child,
                dst_child,
                action=action,
                policy=policy,
                stats=stats,
                progress=progress,
            )
        else:
            # Transfer child file
            result = _transfer_single_file(
                src_child,
                dst_child,
                action=action,
                policy=policy,
                progress=progress,
            )
            if result in ("transferred", "renamed"):
                stats["transferred"] += 1
            elif result == "skipped":
                stats["skipped"] += 1

    if not dst_exists:
        try:
            shutil.copystat(src_dir, dst_dir)  # a folder we created keeps the source's times and mode
        except OSError as err:
            logger.debug(f"[FS Transfer] Times/mode not kept for {dst_dir}: {err}")

    # If action is move, clean up empty source directory
    if action == "move":
        try:
            os.rmdir(src_dir)
        except OSError as err:  # still holds skipped or failed items
            logger.debug(f"[FS Transfer] Kept source folder {src_dir}: {err}")

    return stats


def _same_or_inside(path: str, folder: str) -> bool:
    """True when `path` is `folder` or somewhere inside it (after resolving links)."""
    p, f = os.path.realpath(path), os.path.realpath(folder)
    return p == f or p.startswith(f.rstrip(os.sep) + os.sep)


def execute_transfer(
    sources: list[str],
    destination_dir: str,
    action: str = "copy",
    policy: str = "merge",
    progress: TransferProgress | None = None,
    target_names: list[str] | None = None,
) -> dict[str, Any]:
    """
    Main transfer entry point.
    Processes a list of source paths (files or directories) into destination_dir.
    `target_names` (same length as `sources`) gives each item a new name, e.g. for duplicates.
    """
    collision_policy = CollisionPolicy(policy.lower())
    try:
        os.makedirs(destination_dir, exist_ok=True)
    except OSError:
        pass

    summary: dict[str, Any] = {
        "transferred": 0,
        "skipped": 0,
        "merged_dirs": 0,
        "errors": [],
    }

    for i, src in enumerate(sources):
        if not os.path.lexists(src):
            summary["errors"].append({"path": src, "error": "Item not found"})
            continue

        item_name = (target_names[i] if target_names else "") or os.path.basename(src.rstrip("/\\"))
        dst_target = os.path.join(destination_dir, item_name)

        if os.path.isdir(src) and not os.path.islink(src) and _same_or_inside(destination_dir, src):
            summary["errors"].append({"path": src, "error": "Cannot copy or move a folder into itself"})
            continue
        if os.path.realpath(dst_target) == os.path.realpath(src):
            if action == "move":
                summary["skipped"] += 1  # already there
                if progress is not None:
                    progress.skip_tree(src)
                continue
            summary["errors"].append({"path": src, "error": "Source and destination are the same"})
            continue

        try:
            if os.path.isdir(src) and not os.path.islink(src):
                merge_directory_tree(
                    src,
                    dst_target,
                    action=action,
                    policy=collision_policy,
                    stats=summary,
                    progress=progress,
                )
            else:
                result = _transfer_single_file(
                    src,
                    dst_target,
                    action=action,
                    policy=collision_policy,
                    progress=progress,
                )
                if result in ("transferred", "renamed"):
                    summary["transferred"] += 1
                elif result == "skipped":
                    summary["skipped"] += 1
        except TransferCancelled:
            raise
        except Exception as err:
            logger.error(f"[FS Transfer] Failed to transfer {src} -> {dst_target}: {err}")
            summary["errors"].append({"path": src, "error": str(err)})

    return {
        "status": "ok" if not summary["errors"] else "partial",
        "action": action,
        "policy": collision_policy.value,
        **summary,
    }


class TransferTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SpeedTracker:
    """Sliding-window byte velocity calculator with smoothed moving average."""

    def __init__(self, window_seconds: float = 3.0):
        self.window_seconds = window_seconds
        self.samples: collections.deque[tuple[float, int]] = collections.deque()

    def update(self, current_bytes: int) -> float:
        now = time.time()
        self.samples.append((now, current_bytes))
        while self.samples and (now - self.samples[0][0]) > self.window_seconds:
            self.samples.popleft()
        if len(self.samples) < 2:
            return 0.0
        dt = self.samples[-1][0] - self.samples[0][0]
        db = self.samples[-1][1] - self.samples[0][1]
        if dt <= 0.05:
            return 0.0
        return max(0.0, db / dt)


class TransferTask:
    """Represents an active or historical background filesystem transfer/archive operation."""

    def __init__(
        self,
        task_id: str,
        action: str,
        sources: list[str],
        destination: str,
        collision_policy: str = "merge",
    ):
        self.id = task_id
        self.action = action
        self.sources = sources
        self.destination = destination
        self.collision_policy = collision_policy
        self.owner = ""  # username that started it; empty = system / admin
        self.status = TransferTaskStatus.PENDING
        self.total_bytes = 0
        self.processed_bytes = 0
        self.total_files = 0
        self.processed_files = 0
        self.current_file = ""
        self.speed_bps = 0.0
        self.eta_seconds: float | None = None
        self.percent = 0.0
        self.error: str | None = None
        self.created_at = time.time()
        self.started_at: float | None = None
        self.completed_at: float | None = None
        self.kind = action  # "duplicate" for copies made next to the original
        self.target_names: list[str] = []
        self.result: dict[str, Any] | None = None

        self._pause_event = threading.Event()
        self._pause_event.set()  # set = running, clear = paused
        self._cancel_event = threading.Event()  # set = cancelled
        self._last_notify_ts = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "owner": self.owner,
            "action": self.action,
            "sources": self.sources,
            "destination": self.destination,
            "collision_policy": self.collision_policy,
            "status": self.status.value,
            "total_bytes": self.total_bytes,
            "processed_bytes": self.processed_bytes,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "current_file": self.current_file,
            "speed_bps": round(self.speed_bps, 1),
            "eta_seconds": round(self.eta_seconds, 1) if self.eta_seconds is not None else None,
            "percent": round(self.percent, 1),
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "kind": self.kind,
            "result": self.result,
        }


class _TaskProgress(TransferProgress):
    """Feeds a transfer's progress into its task: counts, speed, time left, pause and cancel."""

    def __init__(self, manager: "TransferTaskManager", task: TransferTask) -> None:
        self.manager = manager
        self.task = task
        self.speed = SpeedTracker()
        self.roots = [os.path.dirname(s.rstrip("/\\")) for s in task.sources]

    def checkpoint(self) -> None:
        task = self.task
        if task._cancel_event.is_set():
            raise TransferCancelled()
        while not task._pause_event.is_set():
            if task._cancel_event.is_set():
                raise TransferCancelled()
            time.sleep(0.2)

    def current(self, path: str) -> None:
        for root in self.roots:
            if root and path.startswith(root + os.sep):
                path = path[len(root) + 1 :]
                break
        self.task.current_file = path
        self._maybe_notify()

    def add_bytes(self, n: int) -> None:
        self.task.processed_bytes += n
        self._maybe_notify()

    def file_done(self) -> None:
        self.task.processed_files += 1
        self._maybe_notify()

    def done_totals(self, files: int, nbytes: int) -> None:
        self.task.processed_files += files
        self.task.processed_bytes += nbytes
        self._maybe_notify()

    def skip_tree(self, path: str) -> None:
        self.done_totals(*tree_totals(path))

    def _maybe_notify(self) -> None:
        task = self.task
        # Kept current on every step: pause and cancel report the task without waiting for a tick
        if task.total_bytes:
            task.percent = min(99.9, task.processed_bytes / task.total_bytes * 100)
        elif task.total_files:
            task.percent = min(99.9, task.processed_files / task.total_files * 100)
        now = time.time()
        if now - task._last_notify_ts < 0.25:
            return
        task._last_notify_ts = now
        task.speed_bps = self.speed.update(task.processed_bytes)
        left = max(0, task.total_bytes - task.processed_bytes)
        task.eta_seconds = (left / task.speed_bps) if task.speed_bps > 1024 else None
        self.manager._notify_update(task)


class TransferTaskManager:
    """
    Central orchestration engine for async filesystem operations, background transfers,
    and archive creation/extraction with real-time SSE telemetry.
    """

    def __init__(self):
        self._tasks: dict[str, TransferTask] = {}
        self._history: collections.deque[TransferTask] = collections.deque(maxlen=100)
        self._lock = threading.Lock()
        self._listeners: set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()

    def register_listener(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
        with self._lock:
            self._listeners.add((queue, loop))

    def unregister_listener(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._listeners = {(q, loop_inst) for (q, loop_inst) in self._listeners if q is not queue}

    def _notify_update(self, task: TransferTask) -> None:
        payload = {"event": "task_update", "task": task.to_dict()}
        with self._lock:
            listeners = list(self._listeners)
        for q, loop in listeners:
            try:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(q.put_nowait, payload)
            except Exception:
                logger.debug(
                    "backend.services.fs_transfer.TransferTaskManager._notify_update: ignored error", exc_info=True
                )

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task.to_dict()
            for t in self._history:
                if t.id == task_id:
                    return t.to_dict()
        return None

    def owner_of(self, task_id: str) -> str | None:
        with self._lock:
            task = self._tasks.get(task_id) or next((t for t in self._history if t.id == task_id), None)
        return None if task is None else (task.owner or "")

    def list_tasks(self, owner: str | None = None) -> list[dict[str, Any]]:
        """All tasks, or only those started by `owner` when given."""
        with self._lock:
            active = [t.to_dict() for t in self._tasks.values() if owner is None or t.owner == owner]
            historical = [
                t.to_dict() for t in self._history if t.id not in self._tasks and (owner is None or t.owner == owner)
            ]
        # Sort newest first
        return sorted(active + historical, key=lambda x: x["created_at"], reverse=True)

    def pause_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task and task.status == TransferTaskStatus.RUNNING:
            task._pause_event.clear()
            task.status = TransferTaskStatus.PAUSED
            self._notify_update(task)
            return True
        return False

    def resume_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task and task.status == TransferTaskStatus.PAUSED:
            task._pause_event.set()
            task.status = TransferTaskStatus.RUNNING
            self._notify_update(task)
            return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
        if task and task.status in (TransferTaskStatus.PENDING, TransferTaskStatus.RUNNING, TransferTaskStatus.PAUSED):
            task._cancel_event.set()
            task._pause_event.set()  # Unblock if waiting on pause
            task.status = TransferTaskStatus.CANCELLED
            task.completed_at = time.time()
            self._notify_update(task)
            return True
        return False

    def clear_completed_tasks(self) -> int:
        with self._lock:
            to_remove = [
                tid
                for tid, t in self._tasks.items()
                if t.status in (TransferTaskStatus.COMPLETED, TransferTaskStatus.FAILED, TransferTaskStatus.CANCELLED)
            ]
            for tid in to_remove:
                t = self._tasks.pop(tid)
                self._history.append(t)
        return len(to_remove)

    def submit_transfer(
        self,
        sources: list[str],
        destination_dir: str,
        action: str = "copy",
        collision_policy: str = "merge",
        owner: str = "",
        target_names: list[str] | None = None,
        kind: str = "",
    ) -> TransferTask:
        task_id = str(uuid.uuid4())
        task = TransferTask(
            task_id=task_id,
            action=action,
            sources=sources,
            destination=destination_dir,
            collision_policy=collision_policy,
        )
        task.owner = (owner or "").lower()
        task.target_names = list(target_names or [])
        task.kind = kind or action
        with self._lock:
            self._tasks[task_id] = task

        worker = threading.Thread(
            target=self._worker_transfer,
            args=(task,),
            name=f"transfer-worker-{task_id[:8]}",
            daemon=True,
        )
        worker.start()
        self._notify_update(task)
        return task

    def submit_archive_create(
        self,
        sources: list[str],
        destination_dir: str,
        archive_name: str,
        fmt: str = "zip",
        owner: str = "",
    ) -> TransferTask:
        task_id = str(uuid.uuid4())
        task = TransferTask(
            task_id=task_id,
            action="archive_create",
            sources=sources,
            destination=destination_dir,
            collision_policy="overwrite",
        )
        task.owner = (owner or "").lower()
        with self._lock:
            self._tasks[task_id] = task

        worker = threading.Thread(
            target=self._worker_archive_create,
            args=(task, archive_name, fmt),
            name=f"archive-create-{task_id[:8]}",
            daemon=True,
        )
        worker.start()
        self._notify_update(task)
        return task

    def submit_archive_extract(
        self,
        archive_path: str,
        destination_dir: str,
        owner: str = "",
    ) -> TransferTask:
        task_id = str(uuid.uuid4())
        task = TransferTask(
            task_id=task_id,
            action="archive_extract",
            sources=[archive_path],
            destination=destination_dir,
            collision_policy="merge",
        )
        task.owner = (owner or "").lower()
        with self._lock:
            self._tasks[task_id] = task

        worker = threading.Thread(
            target=self._worker_archive_extract,
            args=(task, archive_path),
            name=f"archive-extract-{task_id[:8]}",
            daemon=True,
        )
        worker.start()
        self._notify_update(task)
        return task

    # -------------------------------------------------------------------------
    # Worker Implementations
    # -------------------------------------------------------------------------

    def _worker_transfer(self, task: TransferTask) -> None:
        task.started_at = time.time()
        task.status = TransferTaskStatus.RUNNING
        task.current_file = "Counting files…"
        self._notify_update(task)
        progress = _TaskProgress(self, task)

        try:
            # 1. Count what will be copied, so the bar and the time left mean something
            for src in task.sources:
                progress.checkpoint()
                if os.path.lexists(src):
                    files, size = tree_totals(src)
                    task.total_files += files
                    task.total_bytes += size
            self._notify_update(task)

            # 2. Copy or move with the same rules as the direct transfer
            res = execute_transfer(
                task.sources,
                task.destination,
                task.action,
                task.collision_policy,
                progress=progress,
                target_names=task.target_names or None,
            )
            task.result = {k: res.get(k) for k in ("transferred", "skipped", "merged_dirs")}
            errors = res.get("errors") or []
            task.result["errors"] = errors[:20]
            task.processed_files = task.total_files
            task.processed_bytes = task.total_bytes
            task.percent = 100.0
            if errors and not res.get("transferred") and not res.get("skipped"):
                task.status = TransferTaskStatus.FAILED
                task.error = errors[0].get("error") or "Transfer failed"
            else:
                task.status = TransferTaskStatus.COMPLETED
                if errors:
                    task.error = f"{len(errors)} item(s) failed: {errors[0].get('error')}"
        except TransferCancelled:
            task.status = TransferTaskStatus.CANCELLED
        except Exception as e:
            logger.error(f"[TransferManager] Worker error for task {task.id}: {e}")
            task.status = TransferTaskStatus.FAILED
            task.error = str(e)
        finally:
            task.speed_bps = 0.0
            task.eta_seconds = 0.0 if task.status == TransferTaskStatus.COMPLETED else None
            task.current_file = ""
            task.completed_at = time.time()
            self._notify_update(task)
            with self._lock:
                if task.id in self._tasks:
                    self._history.append(self._tasks.pop(task.id))

    def _worker_archive_create(self, task: TransferTask, archive_name: str, fmt: str) -> None:
        speed_tracker = SpeedTracker()
        task.started_at = time.time()
        task.status = TransferTaskStatus.RUNNING
        self._notify_update(task)

        # Collect files
        file_list: list[tuple[str, str, int]] = []
        for src in task.sources:
            if not os.path.lexists(src):
                continue
            base = os.path.basename(src.rstrip("/\\"))
            if os.path.isdir(src):
                for root, sub_dirs, files in os.walk(src):
                    prune_protected(root, sub_dirs)
                    rel = os.path.relpath(root, src)
                    arc_prefix = base if rel == "." else os.path.join(base, rel)
                    for f in files:
                        full_p = os.path.join(root, f)
                        sz = os.path.getsize(full_p) if not os.path.islink(full_p) else 0
                        file_list.append((full_p, os.path.join(arc_prefix, f), sz))
            else:
                sz = os.path.getsize(src) if not os.path.islink(src) else 0
                file_list.append((src, base, sz))

        task.total_files = len(file_list)
        task.total_bytes = sum(f[2] for f in file_list)
        out_path = os.path.join(task.destination, archive_name)
        os.makedirs(task.destination, exist_ok=True)

        try:
            if fmt == "zip" or archive_name.endswith(".zip"):
                with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                    for full_p, arc_name, f_size in file_list:
                        if task._cancel_event.is_set():
                            raise InterruptedError("Cancelled")
                        while not task._pause_event.is_set():
                            if task._cancel_event.is_set():
                                raise InterruptedError("Cancelled")
                            time.sleep(0.2)

                        task.current_file = arc_name
                        zf.write(full_p, arcname=arc_name)
                        task.processed_files += 1
                        task.processed_bytes += f_size
                        now = time.time()
                        if now - task._last_notify_ts >= 0.25:
                            task.speed_bps = speed_tracker.update(task.processed_bytes)
                            rem = max(0, task.total_bytes - task.processed_bytes)
                            task.eta_seconds = (rem / task.speed_bps) if task.speed_bps > 1024 else None
                            task.percent = min(100.0, (task.processed_bytes / max(1, task.total_bytes)) * 100)
                            task._last_notify_ts = now
                            self._notify_update(task)
            else:
                # Tar (.tar.gz / .tar)
                mode = "w:gz" if archive_name.endswith(".gz") or fmt == "tar.gz" else "w"
                with tarfile.open(out_path, mode) as tf:
                    for full_p, arc_name, f_size in file_list:
                        if task._cancel_event.is_set():
                            raise InterruptedError("Cancelled")
                        while not task._pause_event.is_set():
                            if task._cancel_event.is_set():
                                raise InterruptedError("Cancelled")
                            time.sleep(0.2)

                        task.current_file = arc_name
                        tf.add(full_p, arcname=arc_name)
                        task.processed_files += 1
                        task.processed_bytes += f_size
                        now = time.time()
                        if now - task._last_notify_ts >= 0.25:
                            task.speed_bps = speed_tracker.update(task.processed_bytes)
                            rem = max(0, task.total_bytes - task.processed_bytes)
                            task.eta_seconds = (rem / task.speed_bps) if task.speed_bps > 1024 else None
                            task.percent = min(100.0, (task.processed_bytes / max(1, task.total_bytes)) * 100)
                            task._last_notify_ts = now
                            self._notify_update(task)

            task.status = TransferTaskStatus.COMPLETED
            task.percent = 100.0
            task.speed_bps = 0.0
            task.eta_seconds = 0.0
        except InterruptedError:
            task.status = TransferTaskStatus.CANCELLED
            if os.path.exists(out_path):
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
        except Exception as e:
            logger.error(f"[TransferManager] Archive create error: {e}")
            task.status = TransferTaskStatus.FAILED
            task.error = str(e)
            if os.path.exists(out_path):
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
        finally:
            task.completed_at = time.time()
            self._notify_update(task)
            with self._lock:
                if task.id in self._tasks:
                    self._history.append(self._tasks.pop(task.id))

    def _worker_archive_extract(self, task: TransferTask, archive_path: str) -> None:
        speed_tracker = SpeedTracker()
        task.started_at = time.time()
        task.status = TransferTaskStatus.RUNNING
        self._notify_update(task)

        dest_dir = os.path.abspath(task.destination)
        os.makedirs(dest_dir, exist_ok=True)
        archive_size = os.path.getsize(archive_path)

        try:
            if zipfile.is_zipfile(archive_path):
                with zipfile.ZipFile(archive_path, "r") as zf:
                    infolist = zf.infolist()
                    # 1. 3-Tier Zip-Bomb and safety checks
                    if len(infolist) > 100_000:
                        raise ValueError("Archive exceeds maximum entry limit (100,000 files)")
                    total_uncompressed = sum(info.file_size for info in infolist)
                    if total_uncompressed > 50 * 1024 * 1024 * 1024:
                        raise ValueError("Archive exceeds maximum extraction limit (50 GB)")
                    if archive_size > 0 and (total_uncompressed / archive_size) > 100:
                        raise ValueError("Archive exceeds safe compression ratio (> 100:1 potential zip bomb)")

                    # 2. Zip-Slip Path Traversal defense
                    for info in infolist:
                        target = os.path.abspath(os.path.join(dest_dir, info.filename))
                        if os.path.commonpath([dest_dir, target]) != dest_dir:
                            raise ValueError(f"Zip-Slip path traversal attempt detected in: {info.filename}")

                    task.total_files = len(infolist)
                    task.total_bytes = total_uncompressed

                    for info in infolist:
                        if task._cancel_event.is_set():
                            raise InterruptedError("Cancelled")
                        while not task._pause_event.is_set():
                            if task._cancel_event.is_set():
                                raise InterruptedError("Cancelled")
                            time.sleep(0.2)

                        task.current_file = info.filename
                        zf.extract(info, dest_dir)
                        task.processed_files += 1
                        task.processed_bytes += info.file_size
                        now = time.time()
                        if now - task._last_notify_ts >= 0.25:
                            task.speed_bps = speed_tracker.update(task.processed_bytes)
                            rem = max(0, task.total_bytes - task.processed_bytes)
                            task.eta_seconds = (rem / task.speed_bps) if task.speed_bps > 1024 else None
                            task.percent = min(100.0, (task.processed_bytes / max(1, task.total_bytes)) * 100)
                            task._last_notify_ts = now
                            self._notify_update(task)
            else:
                # Tar extraction
                with tarfile.open(archive_path, "r:*") as tf:
                    members = tf.getmembers()
                    if len(members) > 100_000:
                        raise ValueError("Archive exceeds maximum entry limit (100,000 files)")
                    total_uncompressed = sum(m.size for m in members)
                    if total_uncompressed > 50 * 1024 * 1024 * 1024:
                        raise ValueError("Archive exceeds maximum extraction limit (50 GB)")
                    if archive_size > 0 and (total_uncompressed / archive_size) > 100:
                        raise ValueError("Archive exceeds safe compression ratio (> 100:1)")

                    # Check every member before writing anything (SEC-03): no paths,
                    # links or link targets outside dest_dir, no device files.
                    for m in members:
                        target = os.path.abspath(os.path.join(dest_dir, m.name))
                        if os.path.commonpath([dest_dir, target]) != dest_dir:
                            raise ValueError(f"Tar-Slip path traversal attempt detected in: {m.name}")
                        if m.isdev():
                            raise ValueError(f"Device files are not allowed in archives: {m.name}")
                        if m.issym() or m.islnk():
                            if os.path.isabs(m.linkname):
                                raise ValueError(f"Absolute link target not allowed: {m.name}")
                            base = os.path.dirname(target) if m.issym() else dest_dir
                            link_target = os.path.abspath(os.path.join(base, m.linkname))
                            if os.path.commonpath([dest_dir, link_target]) != dest_dir:
                                raise ValueError(f"Link pointing outside the destination: {m.name}")

                    task.total_files = len(members)
                    task.total_bytes = total_uncompressed

                    for m in members:
                        if task._cancel_event.is_set():
                            raise InterruptedError("Cancelled")
                        while not task._pause_event.is_set():
                            if task._cancel_event.is_set():
                                raise InterruptedError("Cancelled")
                            time.sleep(0.2)

                        task.current_file = m.name
                        # "data" filter: re-checks links at write time, drops setuid bits.
                        tf.extract(m, dest_dir, filter="data")
                        task.processed_files += 1
                        task.processed_bytes += m.size
                        now = time.time()
                        if now - task._last_notify_ts >= 0.25:
                            task.speed_bps = speed_tracker.update(task.processed_bytes)
                            rem = max(0, task.total_bytes - task.processed_bytes)
                            task.eta_seconds = (rem / task.speed_bps) if task.speed_bps > 1024 else None
                            task.percent = min(100.0, (task.processed_bytes / max(1, task.total_bytes)) * 100)
                            task._last_notify_ts = now
                            self._notify_update(task)

            task.status = TransferTaskStatus.COMPLETED
            task.percent = 100.0
            task.speed_bps = 0.0
            task.eta_seconds = 0.0
        except InterruptedError:
            task.status = TransferTaskStatus.CANCELLED
        except Exception as e:
            logger.error(f"[TransferManager] Archive extract error: {e}")
            task.status = TransferTaskStatus.FAILED
            task.error = str(e)
        finally:
            task.completed_at = time.time()
            self._notify_update(task)
            with self._lock:
                if task.id in self._tasks:
                    self._history.append(self._tasks.pop(task.id))


# Global singleton instance
transfer_manager = TransferTaskManager()
