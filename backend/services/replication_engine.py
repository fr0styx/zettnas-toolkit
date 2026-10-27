"""
ZettNAS Toolkit - Snapshot Replication Engine (REL-5)

Copies a ZFS dataset or a btrfs subvolume to another pool, here or on another machine over SSH,
as snapshots: the first run sends everything, later runs only what changed since the last
snapshot both sides have. It runs where ZettNAS manages the pools (ZettOS, plain Linux) with the
tools in the image; TrueNAS and Unraid replicate their own pools.

Safe by design:
- the incremental base is the last snapshot this job sent, checked on both sides;
- a target that exists without that snapshot is never overwritten (no `zfs receive -F`), and a
  ZFS replica is received unmounted and read-only so it can't drift;
- both programs' error output is read while they run, so a chatty sender can't stall the pipe;
- old snapshots of the job are pruned on both sides, always keeping the newest (the next base).
"""

import collections
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json

REPLICATION_JOBS_FILE = os.path.join(DATA_DIR, "replication_jobs.json")
REPLICATION_HISTORY_FILE = os.path.join(DATA_DIR, "replication_history.json")
INTERVALS = {"hourly": 3600, "daily": 86400, "weekly": 7 * 86400}
OWNED = ("zettos", "generic_linux")  # where ZettNAS manages the pools itself
_NAME = re.compile(r"^[A-Za-z0-9_\-./]{1,256}$")
_HOST = re.compile(r"^[A-Za-z0-9_\-.:]{1,256}$")
_USER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,31}$")
_CHUNK = 1 << 20


class ReplicationError(RuntimeError):
    pass


@dataclass
class ReplicationJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    source_pool: str = ""
    source_dataset: str = ""
    target_type: str = "local"  # "local", "remote_ssh", "remote_wireguard"
    target_host: str | None = None
    target_port: int = 22
    target_user: str = "root"
    target_pool: str = ""
    target_dataset: str = ""
    bandwidth_limit_kbps: int | None = None  # e.g. 10000 = 10 MB/s
    incremental: bool = True
    retention_count: int = 14  # snapshots of this job kept on each side
    schedule: str = "daily"  # "manual", "hourly", "daily", "weekly"
    hour: int = 1  # daily and weekly (Sundays) runs start at this hour
    created_at: float = field(default_factory=time.time)
    last_run: float | None = None
    last_status: str = "idle"  # "idle", "running", "success", "error"
    last_error: str | None = None
    last_success: float | None = None
    last_snapshot: str | None = None  # the snapshot both sides have: the next incremental base
    bytes_transferred: int = 0


def availability(adapter: Any = None) -> tuple[bool, str]:
    """Whether this NAS can replicate its pools, and why not."""
    from backend.hardware.pal import base

    try:
        if adapter is None:
            from backend.hardware.pal_storage import get_storage_platform

            adapter = get_storage_platform()
        platform = str(adapter.get_platform_type().value)
    except Exception:
        platform = ""
    if platform == "truenas":
        return False, "TrueNAS replicates its own pools: use Data Protection > Replication Tasks there."
    if platform == "unraid":
        return False, "Unraid's pools are replicated with an off-site backup to another NAS."
    if platform not in OWNED:
        return False, "Replication runs only where ZettNAS manages the pools."
    tools = base.storage_tools()
    if not (tools.get("zfs") or tools.get("btrfs")):
        return False, base.storage_tools_problem() or "This image has neither the ZFS nor the btrfs tools."
    return True, ""


def validate(job: dict[str, Any]) -> None:
    """Refuses names that could reach outside a pool or into a shell."""
    for key in ("source_pool", "source_dataset", "target_pool", "target_dataset"):
        val = str(job.get(key) or "")
        if val and (not _NAME.match(val) or ".." in val.split("/")):
            raise ValueError(f"{key} may only hold letters, digits and _ - . /")
    if not job.get("source_pool") or not job.get("target_pool"):
        raise ValueError("Pick a source pool and a target.")
    if job.get("target_type", "local") != "local":
        if not _HOST.match(str(job.get("target_host") or "")):
            raise ValueError("A remote target needs a host name or address.")
        if not _USER.match(str(job.get("target_user") or "")):
            raise ValueError("That user name can't be used.")
    if job.get("schedule", "daily") not in ("manual", *INTERVALS):
        raise ValueError("The schedule is manual, hourly, daily or weekly.")


def _run(cmd: list[str], timeout: int = 600) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ReplicationError(f"{cmd[0]} took too long") from None
    except OSError as err:
        raise ReplicationError(f"{cmd[0]} could not run: {err}") from None
    if res.returncode != 0:
        lines = (res.stderr or res.stdout or f"exit {res.returncode}").strip().splitlines()
        raise ReplicationError(lines[-1][:300] if lines else f"exit {res.returncode}")
    return res.stdout


class _Side:
    """Where commands for the target run: here, or on the other machine over SSH."""

    def __init__(self, job: dict[str, Any]):
        self.remote = job.get("target_type", "local") != "local"
        self.ssh = [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-p",
            str(int(job.get("target_port") or 22)),
            f"{job.get('target_user') or 'root'}@{job.get('target_host')}",
        ]

    def cmd(self, argv: list[str]) -> list[str]:
        return [*self.ssh, shlex.join(argv)] if self.remote else argv

    def run(self, argv: list[str], timeout: int = 600) -> str:
        return _run(self.cmd(argv), timeout)

    def ok(self, argv: list[str]) -> bool:
        try:
            self.run(argv, timeout=60)
            return True
        except ReplicationError:
            return False


def _drain(stream: Any, keep: collections.deque) -> None:
    for raw in iter(stream.readline, b""):
        keep.append(raw.decode("utf-8", errors="replace").rstrip())
    stream.close()


def _pipe(send: list[str], recv: list[str], limit_kbps: int | None = None) -> int:
    """send | recv, counting bytes and keeping to the bandwidth limit. Both error outputs are
    read as they come, so neither program blocks on a full pipe."""
    p1 = subprocess.Popen(send, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p2 = subprocess.Popen(recv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    err1: collections.deque = collections.deque(maxlen=20)
    err2: collections.deque = collections.deque(maxlen=20)
    drains = [
        threading.Thread(target=_drain, args=(p1.stderr, err1), daemon=True),
        threading.Thread(target=_drain, args=(p2.stderr, err2), daemon=True),
    ]
    for d in drains:
        d.start()
    total, started, killed = 0, time.monotonic(), False
    rate = (limit_kbps or 0) * 1024
    out, into = p1.stdout, p2.stdin
    try:
        if out is None or into is None:
            raise OSError("no pipe")
        for chunk in iter(lambda: out.read(_CHUNK), b""):
            into.write(chunk)
            total += len(chunk)
            if rate:
                ahead = total / rate - (time.monotonic() - started)
                if ahead > 0:
                    time.sleep(ahead)
        into.close()
    except (BrokenPipeError, OSError):
        p1.kill()  # the receiver stopped: its error says why
        killed = True
    p2.wait()
    p1.wait()
    for d in drains:
        d.join(5)
    if p1.returncode != 0 and not killed:
        raise ReplicationError(f"send failed: {(err1[-1] if err1 else f'exit {p1.returncode}')[:300]}")
    if p2.returncode != 0:
        raise ReplicationError(f"receive failed: {(err2[-1] if err2 else f'exit {p2.returncode}')[:300]}")
    return total


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _tag(job: dict[str, Any]) -> str:
    return f"zettnas-repl-{str(job.get('id', ''))[:8]}-"


def _prune(names: list[str], keep: int, newest: str) -> list[str]:
    """The job's snapshots to delete, oldest first: all but the newest `keep` (at least one), and
    never `newest`, the snapshot just sent and the next run's base."""
    old = sorted(names)[: max(0, len(names) - max(1, keep))]
    return [n for n in old if n != newest]


class _Zfs:
    def __init__(self, job: dict[str, Any], side: _Side):
        self.job, self.side = job, side
        self.src = "/".join(p for p in (job.get("source_pool"), job.get("source_dataset")) if p)
        self.tgt = "/".join(p for p in (job.get("target_pool"), job.get("target_dataset")) if p)

    def _snaps(self, dataset: str, remote: bool) -> list[str]:
        argv = ["zfs", "list", "-H", "-t", "snapshot", "-o", "name", "-d", "1", "--", dataset]
        try:
            out = self.side.run(argv) if remote else _run(argv)
        except ReplicationError:
            return []
        tag = _tag(self.job)
        return [n.split("@", 1)[1] for n in out.split() if "@" in n and n.split("@", 1)[1].startswith(tag)]

    def replicate(self, snap: str) -> int:
        base = self.job.get("last_snapshot")
        exists = self.side.ok(["zfs", "list", "-H", "-o", "name", "--", self.tgt])
        has_base = bool(base) and base in self._snaps(self.src, False) and base in self._snaps(self.tgt, True)
        if exists and not has_base:
            raise ReplicationError(
                f"{self.tgt} already exists without this job's last snapshot, so it is not overwritten: "
                "pick a new target dataset, or remove that one"
            )
        _run(["zfs", "snapshot", "--", f"{self.src}@{snap}"])
        send = ["zfs", "send", *(["-i", f"@{base}"] if has_base else []), "--", f"{self.src}@{snap}"]
        recv = ["zfs", "receive", "-u", *([] if exists else ["-o", "readonly=on"]), "--", self.tgt]
        return _pipe(send, self.side.cmd(recv), self.job.get("bandwidth_limit_kbps"))

    def prune(self, keep: int, newest: str) -> int:
        n = 0
        for name in _prune(self._snaps(self.src, False), keep, newest):
            _run(["zfs", "destroy", "--", f"{self.src}@{name}"])
            n += 1
        for name in _prune(self._snaps(self.tgt, True), keep, newest):
            self.side.run(["zfs", "destroy", "--", f"{self.tgt}@{name}"])
            n += 1
        return n


class _Btrfs:
    def __init__(self, job: dict[str, Any], side: _Side, adapter: Any):
        self.job, self.side = job, side
        pool = adapter.get_pool_path(job["source_pool"])
        self.src = os.path.join(pool, job.get("source_dataset") or "")
        self.snapdir = os.path.join(pool, ".zettnas-repl", str(job.get("id", ""))[:8])
        target = job.get("target_pool") or ""
        if not side.remote:
            target = adapter.get_pool_path(target)
        self.tgt = os.path.join(target, job.get("target_dataset") or "")

    def _local(self) -> list[str]:
        try:
            return [n for n in os.listdir(self.snapdir) if n.startswith(_tag(self.job))]
        except OSError:
            return []

    def _remote(self) -> list[str]:
        try:
            out = self.side.run(["ls", "-1", "--", self.tgt])
        except ReplicationError:
            return []
        return [n for n in out.split() if n.startswith(_tag(self.job))]

    def replicate(self, snap: str) -> int:
        base = self.job.get("last_snapshot")
        has_base = bool(base) and base in self._local() and base in self._remote()
        if self.side.ok(["test", "-e", os.path.join(self.tgt, snap)]):
            raise ReplicationError(f"{os.path.join(self.tgt, snap)} already exists, so it is not overwritten")
        self.side.run(["mkdir", "-p", "--", self.tgt])
        os.makedirs(self.snapdir, exist_ok=True)
        path = os.path.join(self.snapdir, snap)
        _run(["btrfs", "subvolume", "snapshot", "-r", "--", self.src, path])
        send = ["btrfs", "send", *(["-p", os.path.join(self.snapdir, str(base))] if has_base else []), "--", path]
        return _pipe(send, self.side.cmd(["btrfs", "receive", "--", self.tgt]), self.job.get("bandwidth_limit_kbps"))

    def prune(self, keep: int, newest: str) -> int:
        n = 0
        for name in _prune(self._local(), keep, newest):
            _run(["btrfs", "subvolume", "delete", "--", os.path.join(self.snapdir, name)])
            n += 1
        for name in _prune(self._remote(), keep, newest):
            self.side.run(["btrfs", "subvolume", "delete", "--", os.path.join(self.tgt, name)])
            n += 1
        return n


def _fs_type(adapter: Any, pool_id: str) -> str:
    for p in adapter.list_pools():
        if p.id == pool_id or p.name == pool_id:
            if p.fs_type in ("zfs", "btrfs"):
                return str(p.fs_type)
            raise ReplicationError(f"{pool_id} is {p.fs_type}: only ZFS and btrfs pools can be replicated")
    raise ReplicationError(f"There is no pool {pool_id}")


def replicate(job: dict[str, Any], adapter: Any = None) -> dict[str, Any]:
    """One run of a job: snapshot, send what changed, prune. Returns the snapshot and bytes."""
    validate(job)
    if adapter is None:
        from backend.hardware.pal_storage import get_storage_platform

        adapter = get_storage_platform()
    side = _Side(job)
    kind = _fs_type(adapter, str(job["source_pool"]))
    engine = _Zfs(job, side) if kind == "zfs" else _Btrfs(job, side, adapter)
    snap = _tag(job) + _stamp()
    sent = engine.replicate(snap)
    pruned = 0
    try:
        pruned = engine.prune(int(job.get("retention_count") or 14), snap)
    except ReplicationError as err:  # the copy is made; old snapshots go next time
        logger.warning(f"[Replication] Pruning {job.get('name')} failed: {err}")
    return {"snapshot": snap, "bytes": sent, "pruned": pruned, "fs": kind}


class ReplicationEngine:
    """Keeps the replication jobs, runs them in the background and on their schedule."""

    def __init__(self):
        self._lock = threading.RLock()
        self._running_jobs: dict[str, threading.Thread] = {}

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            data = read_json(REPLICATION_JOBS_FILE, [])
            if not isinstance(data, list):
                return []
            return data

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return next((j for j in self.list_jobs() if j.get("id") == job_id), None)

    def create_job(self, job_data: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            jobs = self.list_jobs()
            job = ReplicationJob(
                id=job_data.get("id") or str(uuid.uuid4()),
                name=job_data.get("name", "Replication Job"),
                source_pool=job_data.get("source_pool", ""),
                source_dataset=job_data.get("source_dataset", ""),
                target_type=job_data.get("target_type", "local"),
                target_host=job_data.get("target_host"),
                target_port=int(job_data.get("target_port", 22)),
                target_user=job_data.get("target_user", "root"),
                target_pool=job_data.get("target_pool", ""),
                target_dataset=job_data.get("target_dataset", ""),
                bandwidth_limit_kbps=int(job_data["bandwidth_limit_kbps"])
                if job_data.get("bandwidth_limit_kbps")
                else None,
                incremental=bool(job_data.get("incremental", True)),
                retention_count=int(job_data.get("retention_count", 14)),
                schedule=job_data.get("schedule", "daily"),
                hour=max(0, min(int(job_data.get("hour", 1)), 23)),
            )
            d = asdict(job)
            jobs.append(d)
            atomic_write_json(REPLICATION_JOBS_FILE, jobs)
            logger.info(f"[Replication] Created job {job.id} ('{job.name}')")
            return d

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            jobs = self.list_jobs()
            kept = [j for j in jobs if j.get("id") != job_id]
            if len(kept) == len(jobs):
                return False
            atomic_write_json(REPLICATION_JOBS_FILE, kept)
            logger.info(f"[Replication] Deleted job {job_id}")
            return True

    def update_job_status(
        self,
        job_id: str,
        status: str,
        error: str | None = None,
        bytes_transferred: int = 0,
        **fields: Any,
    ) -> None:
        with self._lock:
            jobs = self.list_jobs()
            for j in jobs:
                if j.get("id") == job_id:
                    j["last_status"] = status
                    j["last_run"] = time.time()
                    j["last_error"] = error
                    if bytes_transferred > 0:
                        j["bytes_transferred"] = bytes_transferred
                    j.update(fields)
                    break
            atomic_write_json(REPLICATION_JOBS_FILE, jobs)
        if status != "running":
            self._record_history(job_id, status, error, bytes_transferred)

    @json_locked(lambda *a, **k: REPLICATION_HISTORY_FILE)
    def _record_history(self, job_id: str, status: str, error: str | None, bytes_transferred: int) -> None:
        hist = read_json(REPLICATION_HISTORY_FILE, [])
        if not isinstance(hist, list):
            hist = []
        hist.append(
            {
                "job_id": job_id,
                "timestamp": time.time(),
                "status": status,
                "error": error,
                "bytes_transferred": bytes_transferred,
            }
        )
        try:
            atomic_write_json(REPLICATION_HISTORY_FILE, hist[-100:])
        except OSError as e:
            logger.warning(f"[Replication] Could not record the run: {e}")

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        hist = read_json(REPLICATION_HISTORY_FILE, [])
        if not isinstance(hist, list):
            return []
        return hist[-limit:]

    def is_running(self, job_id: str) -> bool:
        t = self._running_jobs.get(job_id)
        return bool(t and t.is_alive())

    def run_job_async(self, job_id: str) -> dict[str, Any]:
        """Starts one run in the background."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        with self._lock:
            if self.is_running(job_id):
                return {"status": "already_running", "job_id": job_id}
            t = threading.Thread(target=self._execute, args=(job,), daemon=True, name=f"Replication-{job_id[:8]}")
            self._running_jobs[job_id] = t
            t.start()
        return {"status": "started", "job_id": job_id}

    def _execute(self, job: dict[str, Any]) -> None:
        job_id = str(job.get("id", ""))
        name = job.get("name") or job_id
        self.update_job_status(job_id, "running")
        try:
            res = replicate(job)
        except Exception as e:
            err = str(e)[:300]
            logger.error(f"[Replication] {name} failed: {err}")
            self.update_job_status(job_id, "error", error=err)
            _notify(f"Replication failed: {name}", err, "warning", job_id)
            return
        self.update_job_status(
            job_id, "success", bytes_transferred=res["bytes"], last_success=time.time(), last_snapshot=res["snapshot"]
        )
        logger.info(f"[Replication] {name}: sent {res['bytes']} bytes as {res['snapshot']}")

    def due(self, job: dict[str, Any], now: float) -> bool:
        interval = INTERVALS.get(str(job.get("schedule") or ""))
        if not interval or self.is_running(str(job.get("id"))):
            return False
        if now - float(job.get("last_run") or 0) < interval * 0.9:
            return False
        if interval == 3600:
            return True
        t = time.localtime(now)
        weekly_ok = interval != INTERVALS["weekly"] or t.tm_wday == 6
        return t.tm_hour == int(job.get("hour", 1)) and weekly_ok

    def run_due(self, now: float | None = None) -> list[str]:
        """Called every minute by the scheduler: starts the jobs whose time has come."""
        now = now or time.time()
        if not any(INTERVALS.get(str(j.get("schedule"))) for j in self.list_jobs()) or not availability()[0]:
            return []
        started = []
        for job in self.list_jobs():
            if self.due(job, now):
                self.run_job_async(str(job["id"]))
                started.append(str(job["id"]))
        return started


def _notify(title: str, message: str, level: str, job_id: str) -> None:
    try:
        from backend.services.notifications import send_notification

        send_notification(title, message, level=level, event_type="backup", dedup_key=f"replication-{job_id}")
    except Exception as e:
        logger.debug(f"[Replication] Notification failed: {e}")


def overdue(now: float | None = None) -> list[dict[str, Any]]:
    """Scheduled jobs that failed or have no success within twice their interval (backup_watch)."""
    now = now or time.time()
    out = []
    for job in get_replication_engine().list_jobs():
        interval = INTERVALS.get(str(job.get("schedule") or ""))
        if not interval:
            continue
        base = {"id": job.get("id"), "name": job.get("name"), "kind": "replication"}
        if job.get("last_status") == "error":
            out.append({**base, "why": "its last run failed"})
        elif now - max(float(job.get("last_success") or 0), float(job.get("created_at") or now)) > 2 * interval:
            out.append({**base, "why": "it hasn't run lately"})
    return out


_REPLICATION_ENGINE: ReplicationEngine | None = None


def get_replication_engine() -> ReplicationEngine:
    global _REPLICATION_ENGINE
    if _REPLICATION_ENGINE is None:
        _REPLICATION_ENGINE = ReplicationEngine()
    return _REPLICATION_ENGINE
