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
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from backend.config import logger


class CollisionPolicy(str, Enum):
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


def check_transfer_conflicts(sources: List[str], destination_dir: str) -> Dict[str, Any]:
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


def _copy_file_resilient(src: str, dst: str) -> None:
    """Copy a file preserving metadata when possible, falling back to data copy on FUSE/cloud remotes."""
    try:
        if os.path.islink(src):
            shutil.copy2(src, dst, follow_symlinks=False)
        else:
            shutil.copy2(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _move_file_resilient(src: str, dst: str) -> None:
    """Move a single file across possibly distinct filesystems or FUSE/rclone mounts, falling back to copy+unlink."""
    try:
        os.replace(src, dst)
    except OSError:
        _copy_file_resilient(src, dst)
        try:
            os.unlink(src)
        except OSError:
            pass


def _transfer_single_file(
    src: str,
    dst: str,
    action: str = "copy",
    policy: CollisionPolicy = CollisionPolicy.OVERWRITE,
) -> str:
    """
    Transfers a single file respecting collision policy.
    Returns: 'transferred', 'skipped', or 'renamed'.
    """
    final_dst = dst
    if os.path.lexists(dst):
        if policy == CollisionPolicy.SKIP:
            return "skipped"
        elif policy == CollisionPolicy.KEEP_BOTH:
            final_dst = _generate_unique_target(dst)
        elif policy in (CollisionPolicy.OVERWRITE, CollisionPolicy.MERGE):
            final_dst = dst

    os.makedirs(os.path.dirname(final_dst), exist_ok=True)

    if action == "move":
        _move_file_resilient(src, final_dst)
    else:
        _copy_file_resilient(src, final_dst)

    return "renamed" if final_dst != dst else "transferred"


def merge_directory_tree(
    src_dir: str,
    dst_dir: str,
    action: str = "copy",
    policy: CollisionPolicy = CollisionPolicy.MERGE,
    stats: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    """
    Recursively merges src_dir into dst_dir:
    - If policy == MERGE: creates subdirectories and transfers non-conflicting child items.
    - If policy == OVERWRITE: replaces existing directory entirely.
    - If policy == SKIP: skips entire directory if destination exists.
    - If policy == KEEP_BOTH: renames target directory e.g. dst_dir (1).
    """
    if stats is None:
        stats = {"transferred": 0, "skipped": 0, "merged_dirs": 0}

    dst_exists = os.path.lexists(dst_dir)

    if dst_exists:
        if policy == CollisionPolicy.SKIP:
            stats["skipped"] += 1
            return stats
        elif policy == CollisionPolicy.KEEP_BOTH:
            dst_dir = _generate_unique_target(dst_dir)
            dst_exists = False
        elif policy == CollisionPolicy.OVERWRITE:
            if os.path.isdir(dst_dir):
                shutil.rmtree(dst_dir)
            else:
                os.unlink(dst_dir)
            dst_exists = False

    # Destination directory now either does not exist or we are performing MERGE
    if not dst_exists:
        if action == "move":
            try:
                os.rename(src_dir, dst_dir)
                stats["transferred"] += 1
                return stats
            except OSError:
                # Cross-device move or FUSE/rclone remote: continue with recursive leaf transfer
                pass
        os.makedirs(dst_dir, exist_ok=True)
    else:
        stats["merged_dirs"] += 1

    try:
        entries = list(os.scandir(src_dir))
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
            )
        else:
            # Transfer child file
            result = _transfer_single_file(
                src_child,
                dst_child,
                action=action,
                policy=policy,
            )
            if result in ("transferred", "renamed"):
                stats["transferred"] += 1
            elif result == "skipped":
                stats["skipped"] += 1

    # If action is move, clean up empty source directory
    if action == "move":
        try:
            os.rmdir(src_dir)
        except OSError:
            pass

    return stats


def execute_transfer(
    sources: List[str],
    destination_dir: str,
    action: str = "copy",
    policy: str = "merge",
) -> Dict[str, Any]:
    """
    Main transfer entry point.
    Processes a list of source paths (files or directories) into destination_dir.
    """
    collision_policy = CollisionPolicy(policy.lower())
    try:
        os.makedirs(destination_dir, exist_ok=True)
    except OSError:
        pass

    summary = {
        "transferred": 0,
        "skipped": 0,
        "merged_dirs": 0,
        "errors": [],
    }

    for src in sources:
        if not os.path.lexists(src):
            summary["errors"].append({"path": src, "error": "Item not found"})
            continue

        item_name = os.path.basename(src.rstrip("/\\"))
        dst_target = os.path.join(destination_dir, item_name)

        try:
            if os.path.isdir(src):
                merge_directory_tree(
                    src,
                    dst_target,
                    action=action,
                    policy=collision_policy,
                    stats=summary,
                )
            else:
                result = _transfer_single_file(
                    src,
                    dst_target,
                    action=action,
                    policy=collision_policy,
                )
                if result in ("transferred", "renamed"):
                    summary["transferred"] += 1
                elif result == "skipped":
                    summary["skipped"] += 1
        except Exception as err:
            logger.error(f"[FS Transfer] Failed to transfer {src} -> {dst_target}: {err}")
            summary["errors"].append({"path": src, "error": str(err)})

    return {
        "status": "ok" if not summary["errors"] else "partial",
        "action": action,
        "policy": collision_policy.value,
        **summary,
    }


class TransferTaskStatus(str, Enum):
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
        self.samples: collections.deque[Tuple[float, int]] = collections.deque()

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
        sources: List[str],
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
        self.eta_seconds: Optional[float] = None
        self.percent = 0.0
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None

        self._pause_event = threading.Event()
        self._pause_event.set()  # set = running, clear = paused
        self._cancel_event = threading.Event()  # set = cancelled
        self._last_notify_ts = 0.0

    def to_dict(self) -> Dict[str, Any]:
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
        }


class TransferTaskManager:
    """
    Central orchestration engine for async filesystem operations, background transfers,
    and archive creation/extraction with real-time SSE telemetry.
    """

    def __init__(self):
        self._tasks: Dict[str, TransferTask] = {}
        self._history: collections.deque[TransferTask] = collections.deque(maxlen=100)
        self._lock = threading.Lock()
        self._listeners: Set[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()

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
                pass

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                return task.to_dict()
            for t in self._history:
                if t.id == task_id:
                    return t.to_dict()
        return None

    def owner_of(self, task_id: str) -> Optional[str]:
        with self._lock:
            task = self._tasks.get(task_id) or next((t for t in self._history if t.id == task_id), None)
        return None if task is None else (task.owner or "")

    def list_tasks(self, owner: Optional[str] = None) -> List[Dict[str, Any]]:
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
        sources: List[str],
        destination_dir: str,
        action: str = "copy",
        collision_policy: str = "merge",
        owner: str = "",
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
        sources: List[str],
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
        speed_tracker = SpeedTracker()
        task.started_at = time.time()
        task.status = TransferTaskStatus.RUNNING
        self._notify_update(task)

        # 1. Pre-scan sources for total bytes and file count
        file_list: List[Tuple[str, str, int, bool]] = []  # (src_full, rel_path, size, is_dir)
        try:
            for src in task.sources:
                if not os.path.lexists(src):
                    continue
                base_name = os.path.basename(src.rstrip("/\\"))
                if os.path.isdir(src) and not os.path.islink(src):
                    file_list.append((src, base_name, 0, True))
                    for root, dirs, files in os.walk(src):
                        rel_root = os.path.relpath(root, src)
                        target_prefix = base_name if rel_root == "." else os.path.join(base_name, rel_root)
                        for d in dirs:
                            full_d = os.path.join(root, d)
                            file_list.append((full_d, os.path.join(target_prefix, d), 0, True))
                        for f in files:
                            full_f = os.path.join(root, f)
                            sz = 0
                            try:
                                sz = os.path.getsize(full_f) if not os.path.islink(full_f) else 0
                            except OSError:
                                pass
                            file_list.append((full_f, os.path.join(target_prefix, f), sz, False))
                else:
                    sz = 0
                    try:
                        sz = os.path.getsize(src) if not os.path.islink(src) else 0
                    except OSError:
                        pass
                    file_list.append((src, base_name, sz, False))

            task.total_files = len([f for f in file_list if not f[3]])
            task.total_bytes = sum(f[2] for f in file_list)
        except Exception as e:
            logger.error(f"[TransferManager] Error scanning sources for {task.id}: {e}")

        self._notify_update(task)

        # 2. Execute transfer item by item
        chunk_size = 256 * 1024  # 256 KB chunks
        policy = CollisionPolicy(task.collision_policy.lower())

        try:
            for src_path, rel_path, f_size, is_dir in file_list:
                if task._cancel_event.is_set():
                    task.status = TransferTaskStatus.CANCELLED
                    break

                dst_path = os.path.join(task.destination, rel_path)
                task.current_file = rel_path

                if is_dir:
                    os.makedirs(dst_path, exist_ok=True)
                    continue

                # Check collision policy for file
                final_dst = dst_path
                if os.path.lexists(dst_path):
                    if policy == CollisionPolicy.SKIP:
                        task.processed_files += 1
                        task.processed_bytes += f_size
                        continue
                    elif policy == CollisionPolicy.KEEP_BOTH:
                        final_dst = _generate_unique_target(dst_path)

                os.makedirs(os.path.dirname(final_dst), exist_ok=True)

                if os.path.islink(src_path):
                    shutil.copy2(src_path, final_dst, follow_symlinks=False)
                    if task.action == "move":
                        os.unlink(src_path)
                    task.processed_files += 1
                    continue

                # Stream file chunk by chunk
                with open(src_path, "rb") as fsrc, open(final_dst, "wb") as fdst:
                    while True:
                        if task._cancel_event.is_set():
                            raise InterruptedError("Cancelled by user")

                        while not task._pause_event.is_set():
                            if task._cancel_event.is_set():
                                raise InterruptedError("Cancelled by user")
                            time.sleep(0.2)

                        buf = fsrc.read(chunk_size)
                        if not buf:
                            break
                        fdst.write(buf)
                        task.processed_bytes += len(buf)

                        now = time.time()
                        if now - task._last_notify_ts >= 0.25:
                            task.speed_bps = speed_tracker.update(task.processed_bytes)
                            rem = max(0, task.total_bytes - task.processed_bytes)
                            task.eta_seconds = (rem / task.speed_bps) if task.speed_bps > 1024 else None
                            task.percent = min(100.0, (task.processed_bytes / max(1, task.total_bytes)) * 100)
                            task._last_notify_ts = now
                            self._notify_update(task)

                try:
                    shutil.copystat(src_path, final_dst)
                except OSError:
                    pass

                if task.action == "move":
                    try:
                        os.unlink(src_path)
                    except OSError:
                        pass

                task.processed_files += 1

            # If move, clean up empty parent directories
            if task.action == "move" and not task._cancel_event.is_set():
                for src in task.sources:
                    if os.path.isdir(src) and not os.path.islink(src):
                        try:
                            shutil.rmtree(src)
                        except OSError:
                            pass

            if task.status != TransferTaskStatus.CANCELLED:
                task.status = TransferTaskStatus.COMPLETED
                task.percent = 100.0
                task.speed_bps = 0.0
                task.eta_seconds = 0.0
        except InterruptedError:
            task.status = TransferTaskStatus.CANCELLED
        except Exception as e:
            logger.error(f"[TransferManager] Worker error for task {task.id}: {e}")
            task.status = TransferTaskStatus.FAILED
            task.error = str(e)
        finally:
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
        file_list: List[Tuple[str, str, int]] = []
        for src in task.sources:
            if not os.path.lexists(src):
                continue
            base = os.path.basename(src.rstrip("/\\"))
            if os.path.isdir(src):
                for root, _, files in os.walk(src):
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
