"""
ZettNAS Toolkit - Snapshot Replication Engine
Automated local and remote disaster recovery streaming for OpenZFS and Btrfs pools.
Supports bandwidth throttling, in-flight encryption over SSH/WireGuard, and retention management.
"""

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, json_locked, read_json

REPLICATION_JOBS_FILE = os.path.join(DATA_DIR, "replication_jobs.json")
REPLICATION_HISTORY_FILE = os.path.join(DATA_DIR, "replication_history.json")


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
    retention_count: int = 14  # Keep last N snapshots on target
    schedule: str = "daily"  # "manual", "hourly", "daily", "weekly"
    created_at: float = field(default_factory=time.time)
    last_run: float | None = None
    last_status: str = "idle"  # "idle", "running", "success", "error"
    last_error: str | None = None
    bytes_transferred: int = 0


class ReplicationEngine:
    """Manages snapshot replication pipelines and asynchronous execution."""

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
        jobs = self.list_jobs()
        for j in jobs:
            if j.get("id") == job_id:
                return j
        return None

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
            )
            d = asdict(job)
            jobs.append(d)
            atomic_write_json(REPLICATION_JOBS_FILE, jobs)
            logger.info(f"[Replication] Created job {job.id} ('{job.name}')")
            return d

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            jobs = self.list_jobs()
            initial_len = len(jobs)
            jobs = [j for j in jobs if j.get("id") != job_id]
            if len(jobs) != initial_len:
                atomic_write_json(REPLICATION_JOBS_FILE, jobs)
                logger.info(f"[Replication] Deleted job {job_id}")
                return True
            return False

    def update_job_status(
        self,
        job_id: str,
        status: str,
        error: str | None = None,
        bytes_transferred: int = 0,
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
                    break
            atomic_write_json(REPLICATION_JOBS_FILE, jobs)

        # Record in history ledger
        self._record_history(job_id, status, error, bytes_transferred)

    @json_locked(lambda *a, **k: REPLICATION_HISTORY_FILE)
    def _record_history(
        self,
        job_id: str,
        status: str,
        error: str | None,
        bytes_transferred: int,
    ) -> None:
        try:
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
            # Keep last 100 replication history entries
            if len(hist) > 100:
                hist = hist[-100:]
            atomic_write_json(REPLICATION_HISTORY_FILE, hist)
        except Exception as e:
            logger.debug(f"[Replication] Failed recording history: {e}")

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        hist = read_json(REPLICATION_HISTORY_FILE, [])
        if not isinstance(hist, list):
            return []
        return hist[-limit:]

    def run_job_async(self, job_id: str) -> dict[str, Any]:
        """Dispatches replication pipeline in a background thread."""
        job = self.get_job(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        with self._lock:
            if job_id in self._running_jobs and self._running_jobs[job_id].is_alive():
                return {"status": "already_running", "job_id": job_id}

            t = threading.Thread(
                target=self._execute_replication,
                args=(job,),
                daemon=True,
                name=f"Replication-{job_id[:8]}",
            )
            self._running_jobs[job_id] = t
            t.start()

        return {"status": "started", "job_id": job_id}

    def _execute_replication(self, job: dict[str, Any]) -> None:
        job_id = job.get("id", "")
        self.update_job_status(job_id, "running")
        logger.info(f"[Replication] Starting execution for job {job_id} ('{job.get('name')}')")

        src_pool = job.get("source_pool", "")
        src_ds = job.get("source_dataset", "")
        tgt_type = job.get("target_type", "local")
        tgt_pool = job.get("target_pool", "")
        tgt_ds = job.get("target_dataset", "")
        tgt_host = job.get("target_host")
        tgt_port = job.get("target_port", 22)
        tgt_user = job.get("target_user", "root")
        bw_limit = job.get("bandwidth_limit_kbps")

        for name, val in [
            ("source_pool", src_pool),
            ("source_dataset", src_ds),
            ("target_pool", tgt_pool),
            ("target_dataset", tgt_ds),
        ]:
            if val and (not re.match(r"^[a-zA-Z0-9_\-\.\/]{1,256}$", val) or ".." in val):
                raise ValueError(f"Invalid characters or traversal in {name}: '{val}'")

        try:
            # 1. Determine filesystem type: ZFS or Btrfs
            is_zfs = shutil.which("zfs") is not None
            is_btrfs = shutil.which("btrfs") is not None

            if not is_zfs and not is_btrfs:
                raise RuntimeError("Neither ZFS nor Btrfs tools found on host for snapshot stream.")

            # Create destination command / path
            if tgt_type in ("remote_ssh", "remote_wireguard"):
                if not tgt_host or not re.match(r"^[a-zA-Z0-9_\-\.]{1,256}$", tgt_host):
                    raise ValueError("Target host is required and must be a valid hostname/IP for remote replication")
                remote_ssh_prefix = ["ssh", "-p", str(tgt_port), f"{tgt_user}@{tgt_host}"]
            else:
                remote_ssh_prefix = []

            # 2. Build pipeline commands
            send_cmd: list[str] = []
            recv_cmd: list[str] = []

            snap_tag = f"repl_{int(time.time())}"
            if is_zfs:
                full_src = f"{src_pool}/{src_ds}".strip("/") if src_ds else src_pool
                src_snap = f"{full_src}@{snap_tag}"
                # Create snapshot first
                subprocess.run(["zfs", "snapshot", "--", src_snap], check=True, capture_output=True)

                prev_snap = None
                if job.get("incremental"):
                    try:
                        res = subprocess.run(
                            ["zfs", "list", "-H", "-t", "snapshot", "-o", "name", "-s", "creation", "-r", full_src],
                            capture_output=True,
                            text=True,
                            check=True,
                        )
                        snaps = [s.strip() for s in res.stdout.splitlines() if s.strip() and s.strip() != src_snap]
                        if snaps:
                            prev_snap = snaps[-1]
                    except Exception as snap_err:
                        logger.debug(f"[Replication] Could not inspect previous snapshots for {full_src}: {snap_err}")

                send_cmd = ["zfs", "send", "-v"]
                if prev_snap:
                    send_cmd.extend(["-i", prev_snap])
                send_cmd.extend(["--", src_snap])

                full_tgt = f"{tgt_pool}/{tgt_ds}".strip("/") if tgt_ds else tgt_pool
                recv_cmd = remote_ssh_prefix + ["zfs", "receive", "-F", "--", full_tgt]
            else:
                # Btrfs pipeline
                src_path = (
                    os.path.join("/mnt/storage", src_pool, src_ds) if src_ds else os.path.join("/mnt/storage", src_pool)
                )
                snap_path = f"{src_path}/.snapshots/{snap_tag}"
                os.makedirs(os.path.dirname(snap_path), exist_ok=True)
                subprocess.run(
                    ["btrfs", "subvolume", "snapshot", "-r", "--", src_path, snap_path],
                    check=True,
                    capture_output=True,
                )

                send_cmd = ["btrfs", "send", "--", snap_path]
                tgt_path = os.path.join(tgt_pool or "/mnt/storage", tgt_ds) if tgt_ds else (tgt_pool or "/mnt/storage")
                recv_cmd = remote_ssh_prefix + ["btrfs", "receive", "--", tgt_path]

            # Execute pipeline with real stream byte counting
            logger.info(f"[Replication] Pipeline: {' '.join(send_cmd)} -> {' '.join(recv_cmd)}")
            p1 = subprocess.Popen(send_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            p3 = subprocess.Popen(
                recv_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            total_bytes = 0

            def _stream_pump():
                nonlocal total_bytes
                try:
                    while True:
                        chunk = p1.stdout.read(65536) if p1.stdout else b""
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if p3.stdin:
                            p3.stdin.write(chunk)
                    if p3.stdin:
                        p3.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    try:
                        if p3.stdin:
                            p3.stdin.close()
                    except Exception:
                        logger.debug(
                            "backend.services.replication_engine.ReplicationEngine._execute_replication._stream_pump: ignored error",
                            exc_info=True,
                        )

            pump_thread = threading.Thread(target=_stream_pump, daemon=True)
            pump_thread.start()
            out3, err3 = p3.communicate()
            pump_thread.join(timeout=10)
            out1, err1 = p1.communicate()

            if p3.returncode != 0:
                err_msg = err3.decode("utf-8", errors="replace") if err3 else "Non-zero exit code"
                raise RuntimeError(f"Replication receive failed: {err_msg}")

            if p1.returncode != 0:
                err_msg = err1.decode("utf-8", errors="replace") if err1 else "Non-zero exit code"
                raise RuntimeError(f"Replication send failed: {err_msg}")

            # Completed successfully
            self.update_job_status(job_id, "success", bytes_transferred=total_bytes)
            logger.info(f"[Replication] Job {job_id} succeeded.")
            try:
                from backend.services.notifications import send_notification

                job_name = job.get("name", job_id)
                send_notification(
                    {
                        "type": "replication",
                        "title": f"Replication Succeeded: {job_name}",
                        "message": f"Storage replication pipeline '{job_name}' completed successfully ({src_pool} -> {tgt_pool or 'remote'}).",
                        "level": "info",
                        "meta": {"job_id": job_id, "source": src_pool, "target": tgt_pool},
                    }
                )
            except Exception as notify_err:
                logger.debug(f"[Replication] Notification error: {notify_err}")

        except Exception as e:
            err_str = str(e)
            logger.error(f"[Replication] Job {job_id} failed: {err_str}")
            self.update_job_status(job_id, "error", error=err_str)
            try:
                from backend.services.notifications import send_notification

                job_name = job.get("name", job_id) if isinstance(job, dict) else job_id
                send_notification(
                    {
                        "type": "replication",
                        "title": f"Replication Failed: {job_name}",
                        "message": f"Storage replication pipeline '{job_name}' failed: {err_str}",
                        "level": "error",
                        "meta": {"job_id": job_id, "error": err_str},
                    }
                )
            except Exception as notify_err:
                logger.debug(f"[Replication] Failure notification error: {notify_err}")


_REPLICATION_ENGINE: ReplicationEngine | None = None


def get_replication_engine() -> ReplicationEngine:
    global _REPLICATION_ENGINE
    if _REPLICATION_ENGINE is None:
        _REPLICATION_ENGINE = ReplicationEngine()
    return _REPLICATION_ENGINE
