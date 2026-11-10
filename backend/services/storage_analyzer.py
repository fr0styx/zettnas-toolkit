"""Where a share's space goes: the biggest folders, the biggest files and the kinds of files.

It reads the share's folder listing (names and sizes, never the files' contents), which wakes its
disks if they sleep, so it runs only when someone starts it, as a job they can cancel. The last
result for each share is kept, so opening it again reads nothing. Duplicates are the index's job
(the Duplicates window); this only names the space.
"""

from __future__ import annotations

import heapq
import os
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

RESULT_DIR = os.path.join(DATA_DIR, "storage_analysis")
DEPTH = 3  # folder totals kept this many levels below the share
TOP_FOLDERS = 300
TOP_FILES = 50
# what a share holds that isn't its files: snapshots and the system's own folders
SKIP_DIRS = {".zfs", ".snapshots", ".snapshot", "@eaDir", "#recycle", ".Trash-1000", "lost+found"}

KINDS: dict[str, set[str]] = {
    "video": {"mp4", "mkv", "mov", "avi", "m4v", "wmv", "webm", "ts", "m2ts", "mpg", "mpeg", "flv"},
    "photo": {
        "jpg",
        "jpeg",
        "png",
        "heic",
        "heif",
        "gif",
        "webp",
        "tif",
        "tiff",
        "bmp",
        "dng",
        "cr2",
        "cr3",
        "nef",
        "arw",
        "raf",
        "orf",
        "rw2",
    },
    "audio": {"mp3", "flac", "wav", "m4a", "aac", "ogg", "opus", "wma", "aiff", "alac"},
    "document": {
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "odt",
        "ods",
        "odp",
        "txt",
        "md",
        "rtf",
        "csv",
        "epub",
        "pages",
        "numbers",
        "key",
    },
    "archive": {"zip", "7z", "rar", "tar", "gz", "tgz", "bz2", "xz", "zst"},
    "disk_image": {"iso", "img", "qcow2", "vmdk", "vdi", "vhd", "vhdx", "raw"},
    "backup": {"zettbak", "tib", "bak", "sparsebundle", "backup"},
}
_EXT_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}


def kind_of(name: str) -> str:
    _, _, ext = name.rpartition(".")
    return _EXT_KIND.get(ext.lower(), "other") if ext and ext != name else "other"


def analyze(
    root: str, cancel: threading.Event | None = None, progress: Callable[[int, int], None] | None = None
) -> dict[str, Any]:
    """Walks root (without following links) and adds up the space. progress(files, bytes) is called
    now and then; cancel stops it early (the result says so)."""
    cancel = cancel or threading.Event()
    folders: dict[str, list[int]] = {}  # relative folder -> [bytes, files]
    kinds: dict[str, list[int]] = {}
    largest: list[tuple[int, str]] = []
    files = total = errors = 0
    stack = [""]
    last_report = time.monotonic()
    while stack and not cancel.is_set():
        rel_dir = stack.pop()
        try:
            entries = list(os.scandir(os.path.join(root, rel_dir) if rel_dir else root))
        except OSError:
            errors += 1
            continue
        for e in entries:
            rel = f"{rel_dir}/{e.name}" if rel_dir else e.name
            try:
                if e.is_dir(follow_symlinks=False):
                    if e.name not in SKIP_DIRS:
                        stack.append(rel)
                    continue
                if not e.is_file(follow_symlinks=False):
                    continue
                size = e.stat(follow_symlinks=False).st_size
            except OSError:
                errors += 1
                continue
            files += 1
            total += size
            k = kinds.setdefault(kind_of(e.name), [0, 0])
            k[0] += size
            k[1] += 1
            if len(largest) < TOP_FILES:
                heapq.heappush(largest, (size, rel))
            elif size > largest[0][0]:
                heapq.heapreplace(largest, (size, rel))
            parts = rel_dir.split("/") if rel_dir else []
            for depth in range(1, min(DEPTH, len(parts)) + 1):
                f = folders.setdefault("/".join(parts[:depth]), [0, 0])
                f[0] += size
                f[1] += 1
        if progress and time.monotonic() - last_report > 2:
            progress(files, total)
            last_report = time.monotonic()
    top = heapq.nlargest(TOP_FOLDERS, folders.items(), key=lambda kv: kv[1][0])
    return {
        "root": root,
        "scanned_at": time.time(),
        "complete": not cancel.is_set(),
        "files": files,
        "bytes": total,
        "errors": errors,
        "folders": [{"path": p, "bytes": b, "files": n} for p, (b, n) in top],
        "largest": [{"path": p, "bytes": b} for b, p in sorted(largest, reverse=True)],
        "kinds": {k: {"bytes": b, "files": n} for k, (b, n) in sorted(kinds.items(), key=lambda kv: -kv[1][0])},
    }


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _result_path(share: str) -> str:
    return os.path.join(RESULT_DIR, re.sub(r"[^A-Za-z0-9_.-]", "_", share)[:100] + ".json")


def last_result(share: str) -> dict[str, Any] | None:
    return read_json(_result_path(share), default=None)


_RUNNING: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def running(share: str) -> bool:
    with _LOCK:
        return share in _RUNNING


def start(share: str, root: str, owner: str | None = None) -> str:
    """Starts the analysis of one share in the background; returns its job id. One at a time per share."""
    from backend.services.jobs import job_manager

    with _LOCK:
        if share in _RUNNING:
            raise RuntimeError("already_running")
        cancel = _RUNNING[share] = threading.Event()
    job = job_manager.register(
        "storage_analysis",
        f"Space in {share}",
        owner=owner,
        cancel=cancel.set,
        title_id="jobs.storage_analysis",
        title_params={"share": share},
    )

    def report(files: int, size: int) -> None:
        job_manager.update(
            job.id,
            status="running",
            detail=f"{files} files, {_human(size)}",
            detail_id="jobs.storage_analysis_detail",
            detail_params={"files": files, "size": _human(size)},
        )

    def run() -> None:
        status, error = "done", None
        try:
            result = analyze(root, cancel, report)
            result["share"] = share
            os.makedirs(RESULT_DIR, mode=0o700, exist_ok=True)
            atomic_write_json(_result_path(share), result)
            if not result["complete"]:
                status = "cancelled"
        except OSError as e:
            status, error = "error", str(e)
            logger.warning("storage_analyzer: %s failed: %s", share, e)
        finally:
            with _LOCK:
                _RUNNING.pop(share, None)
            job_manager.finish(job.id, status=status, error=error)

    threading.Thread(target=run, name=f"storage-analysis-{share}", daemon=True).start()
    return job.id
