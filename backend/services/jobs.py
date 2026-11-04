"""One view of long-running work: file transfers, media imports, AI re-embedding, cloud syncs,
backup tasks and jobs registered directly (ARCH-4, ARCH-5); jobs_more adds Docker clean-up,
downloads, drive tests and storage checks (NJOB-2).

Every job has the same typed shape (Job). Each engine keeps running its own work; a source
adapter maps its state into Job, and cancel requests go back to that engine. Jobs seen
finishing are kept in a short history that survives restarts.
"""

import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

ACTIVE = ("queued", "running", "paused")
FINAL = ("done", "error", "cancelled")
HISTORY_FILE = os.path.join(DATA_DIR, "jobs_history.json")
HISTORY_KEEP = 100


@dataclass
class Job:
    id: str
    kind: str  # transfer, media_import, ai_reindex, cloud_sync, backup, or a registered kind
    title: str
    status: str = "running"  # queued, running, paused, done, error, cancelled
    owner: str | None = None  # username; None = a system job (admins only)
    percent: float | None = None
    detail: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    can_cancel: bool = False
    # the title's message key and values, so the Jobs centre shows it in the reader's language
    # (NUX-3); `title` is the English, for logs and older pages
    title_id: str = ""
    title_params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Registered:
    job: Job
    cancel: Callable[[], Any] | None = None


@dataclass
class JobManager:
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _jobs: dict[str, _Registered] = field(default_factory=dict)
    _history: list[dict[str, Any]] = field(default_factory=list)
    _history_loaded: bool = False

    # --- jobs registered directly -------------------------------------------------
    def register(
        self,
        kind: str,
        title: str,
        owner: str | None = None,
        cancel: Callable[[], Any] | None = None,
        title_id: str = "",
        title_params: dict[str, Any] | None = None,
    ) -> Job:
        job = Job(
            id=f"job:{uuid.uuid4().hex[:10]}",
            kind=kind,
            title=title,
            title_id=title_id,
            title_params=title_params or {},
            owner=owner,
            started_at=time.time(),
            can_cancel=cancel is not None,
        )
        with self._lock:
            self._jobs[job.id] = _Registered(job, cancel)
        return job

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            reg = self._jobs.get(job_id)
            if reg:
                for k, v in fields.items():
                    if hasattr(reg.job, k):
                        setattr(reg.job, k, v)

    def finish(self, job_id: str, status: str = "done", error: str | None = None) -> None:
        with self._lock:
            reg = self._jobs.pop(job_id, None)
            if not reg:
                return
            reg.job.status, reg.job.error, reg.job.finished_at, reg.job.can_cancel = status, error, time.time(), False
            if status == "done":
                reg.job.percent = 100.0
            self._remember(reg.job.to_dict())

    # --- listing and cancelling ---------------------------------------------------------
    def list(self, owner: str | None = None, everyone: bool = False) -> dict[str, list[dict[str, Any]]]:
        """Active jobs and recent history; `everyone` (admins) also sees other people's and system jobs."""
        with self._lock:
            jobs = [r.job.to_dict() for r in self._jobs.values()]
        for name, (lister, _cancel) in SOURCES.items():
            try:
                jobs.extend(j.to_dict() for j in lister())
            except Exception:
                logger.debug(f"[Jobs] source {name} failed", exc_info=True)
        for j in jobs:
            if j["status"] in FINAL:
                self._remember(j)

        def visible(j: dict[str, Any]) -> bool:
            return everyone or (owner is not None and j.get("owner") == owner)

        active = [j for j in jobs if j["status"] in ACTIVE and visible(j)]
        with self._lock:
            self._load_history()
            history = [j for j in reversed(self._history) if visible(j)]
        return {"active": sorted(active, key=lambda j: j.get("started_at") or 0, reverse=True), "history": history}

    def cancel(self, job_id: str, owner: str | None = None, everyone: bool = False) -> bool:
        with self._lock:
            reg = self._jobs.get(job_id)
        if reg:
            if not (everyone or reg.job.owner == owner) or not reg.cancel:
                return False
            reg.cancel()
            return True
        prefix = job_id.split(":", 1)[0]
        lister, canceller = SOURCES.get(prefix, (None, None))
        if not canceller or not lister:
            return False
        job = next((j for j in lister() if j.id == job_id), None)
        if not job or not job.can_cancel or not (everyone or job.owner == owner):
            return False
        return bool(canceller(job_id.split(":", 1)[1]))

    # --- history -------------------------------------------------------------------------
    def _remember(self, job: dict[str, Any]) -> None:
        with self._lock:
            self._load_history()
            if any(h["id"] == job["id"] for h in self._history):
                return
            self._history.append(job)
            self._history = self._history[-HISTORY_KEEP:]
            try:
                atomic_write_json(HISTORY_FILE, self._history)
            except OSError:
                logger.debug("[Jobs] could not save the job history", exc_info=True)

    def _load_history(self) -> None:
        if not self._history_loaded:
            data = read_json(HISTORY_FILE, [])
            self._history = data if isinstance(data, list) else []
            self._history_loaded = True


# --- source adapters ------------------------------------------------------------------------
_TRANSFER_STATUS = {
    "pending": "queued",
    "queued": "queued",
    "running": "running",
    "paused": "paused",
    "completed": "done",
    "done": "done",
    "failed": "error",
    "interrupted": "error",
    "error": "error",
    "cancelled": "cancelled",
}


def _transfers() -> list[Job]:
    from backend.services.fs_transfer import transfer_manager

    out = []
    for t in transfer_manager.list_tasks():
        status = _TRANSFER_STATUS.get(str(t.get("status")), "running")
        n = len(t.get("sources") or [])
        verb = {"move": "Move", "copy": "Copy"}.get(str(t.get("action")), str(t.get("action") or "Transfer").title())
        out.append(
            Job(
                id=f"transfer:{t['id']}",
                kind="transfer",
                title=f"{verb} {n} item(s) to {t.get('destination')}",
                title_id=f"jobs.t.{t.get('action')}" if t.get("action") in ("move", "copy") else "jobs.t.transfer",
                title_params={"n": n, "dest": t.get("destination") or ""},
                status=status,
                owner=t.get("owner"),
                percent=t.get("percent"),
                detail=t.get("current_file") or "",
                started_at=t.get("started_at") or t.get("created_at"),
                finished_at=t.get("completed_at"),
                error=t.get("error"),
                can_cancel=status in ACTIVE,
            )
        )
    return out


def _cancel_transfer(task_id: str) -> bool:
    from backend.services.fs_transfer import transfer_manager

    return transfer_manager.cancel_task(task_id)


def _media_import() -> list[Job]:
    from backend.state import Z_STATE

    if not Z_STATE.copy_active:
        return []
    p = Z_STATE.copy.snapshot()
    total = p.get("total") or 0
    pct = round(100.0 * (p.get("copied") or 0) / total, 1) if total else None
    return [
        Job(
            id="copy:media",
            kind="media_import",
            title="Import from the SD card / USB drive",
            title_id="jobs.t.media_import",
            status="paused" if Z_STATE.copy_paused else "running",
            percent=pct,
            detail=str(p.get("file") or ""),
            started_at=p.get("start"),
            can_cancel=True,
        )
    ]


def _cancel_media_import(_id: str) -> bool:
    from backend.state import Z_STATE

    Z_STATE.copy_abort_flag = True
    Z_STATE.copy_overwrite_choice = "cancel"
    Z_STATE.copy_confirm_event.set()
    return True


def _reindex() -> list[Job]:
    from backend.services.rag_reindex_status import REINDEX_STATUS

    status = str(REINDEX_STATUS.get("status") or "idle")
    if status not in ("running", "paused"):
        return []
    return [
        Job(
            id="reindex:ai",
            kind="ai_reindex",
            title="Re-embedding the AI index",
            title_id="jobs.t.reindex",
            status=status,
            percent=REINDEX_STATUS.get("percentage"),
            detail=f"{REINDEX_STATUS.get('completed', 0)} of {REINDEX_STATUS.get('total', 0)} chunks",
        )
    ]


def _cloud_syncs() -> list[Job]:
    from backend.services.rclone_engine import get_rclone_engine

    out = []
    for j in get_rclone_engine().get_sync_jobs():
        raw = str(j.get("status") or "running")
        status = {
            "running": "running",
            "completed": "done",
            "success": "done",
            "failed": "error",
            "error": "error",
        }.get(raw, raw)
        out.append(
            Job(
                id=f"sync:{j['id']}",
                kind="cloud_sync",
                title=f"{str(j.get('action') or 'sync').title()} {j.get('src')} → {j.get('dst')}",
                title_id=f"jobs.t.cloud_{j.get('action') or 'sync'}"
                if (j.get("action") or "sync") in ("sync", "copy", "move")
                else "",
                title_params={"src": j.get("src") or "", "dst": j.get("dst") or ""},
                status=status if status in ACTIVE + FINAL else "running",
                percent=j.get("percent"),
                started_at=j.get("started_at"),
                finished_at=j.get("completed_at"),
                error=j.get("error"),
            )
        )
    return out


def _backups() -> list[Job]:
    from backend.services.backup_engine import get_backup_jobs

    return [
        Job(
            id=f"backup:{j['id']}",
            kind="backup",
            title=f"Backup: {j.get('name')}",
            title_id="jobs.t.backup",
            title_params={"name": j.get("name") or ""},
            status="running",
        )
        for j in get_backup_jobs()
        if j.get("last_status") == "running"
    ]


# prefix -> (list jobs, cancel by id or None)
def _ai_index() -> list[Job]:
    """The AI index learning new and changed files (NJOB-1), when the engine is up and busy."""
    from backend.services import rag_engine

    eng = rag_engine._RAG_ENGINE  # never start the engine just to look
    state = str(getattr(eng, "_sync_state", "idle") or "idle") if eng is not None else "idle"
    if state not in ("running", "paused", "stopping"):
        return []
    prog = dict(getattr(eng, "_sync_progress", {}) or {})
    status = "paused" if state == "paused" else "running"
    detail = (
        f"{prog.get('indexed_files', 0)} indexed, {prog.get('skipped_unchanged', 0)} unchanged, "
        f"{prog.get('deferred_standby', 0)} waiting for sleeping disks"
    )
    return [
        Job(
            id="aiindex:sync",
            kind="ai_index",
            title="Indexing files for AI search",
            title_id="jobs.t.ai_index",
            status=status,
            detail=detail,
            started_at=prog.get("started_at"),
            can_cancel=state in ("running", "paused"),
        )
    ]


def _cancel_ai_index(_id: str) -> bool:
    from backend.services import rag_engine

    if rag_engine._RAG_ENGINE is None:
        return False
    rag_engine._RAG_ENGINE.stop_sync()
    return True


SOURCES: dict[str, tuple[Callable[[], list[Job]], Callable[[str], bool] | None]] = {
    "transfer": (_transfers, _cancel_transfer),
    "copy": (_media_import, _cancel_media_import),
    "reindex": (_reindex, None),
    "sync": (_cloud_syncs, None),
    "backup": (_backups, None),
    "aiindex": (_ai_index, _cancel_ai_index),
}  # thumb_prefetch adds "thumbs" itself (it imports this module, not the other way round)

job_manager = JobManager()


# --- reporting helpers for work that runs on its own (NJOB-2) ------------------------------------
PAUSED_WHY = {
    "busy": "Waiting until the NAS is idle",
    "standby": "Waiting for a sleeping disk",
    "outside-schedule": "Waiting for the AI learning hours",
    "error": "The last try failed; trying again shortly",
}
PROGRESS_EVERY_S = 60.0


class PassReport:
    """A background pass in the Jobs centre: listed from its first piece of work, shown as paused
    while it waits, and moved to the history when it runs out of work."""

    def __init__(self, kind: str, title: str, title_id: str) -> None:
        self.kind, self.title, self.title_id = kind, title, title_id
        self.job_id: str | None = None
        self._progress: tuple[str, float | None] = ("", None)
        self._progress_at = 0.0

    def note(
        self, state: str, progress: Callable[[], tuple[str, float | None]], worked: tuple[str, ...] = ("done",)
    ) -> None:
        """One step's outcome: work done (`worked`), a wait (PAUSED_WHY) or nothing left to do.
        `progress` (detail, percent) is asked at most once a minute."""
        if state in worked:
            if self.job_id is None:
                self.job_id = job_manager.register(self.kind, self.title, title_id=self.title_id).id
                self._progress_at = 0.0
            now = time.time()
            if now - self._progress_at >= PROGRESS_EVERY_S:
                self._progress, self._progress_at = progress(), now
            detail, percent = self._progress
            job_manager.update(self.job_id, status="running", detail=detail, percent=percent)
        elif state in PAUSED_WHY:
            if self.job_id is not None:
                job_manager.update(self.job_id, status="paused", detail=PAUSED_WHY[state])
        elif self.job_id is not None:
            job_manager.update(self.job_id, detail=self._progress[0])
            job_manager.finish(self.job_id)
            self.job_id = None


def follow(
    events: Iterable[dict[str, Any]],
    kind: str,
    title: str,
    title_id: str = "",
    title_params: dict[str, Any] | None = None,
    owner: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Passes a progress stream's events on and mirrors them in the Jobs centre: percent and message
    as they come, done or failed at the end, cancelled when the stream stops early (its window was
    closed, which stops the work)."""
    job = job_manager.register(kind, title, owner=owner, title_id=title_id, title_params=title_params)
    status, error = "cancelled", None
    try:
        for ev in events:
            if ev.get("step") == "error":
                status, error = "error", str(ev.get("message") or ev.get("error") or "Failed")
            elif ev.get("done"):
                status = "done"
            else:
                job_manager.update(job.id, percent=ev.get("percent"), detail=str(ev.get("message") or ""))
            yield ev
    finally:
        job_manager.finish(job.id, status=status, error=error)
