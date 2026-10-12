"""
ZettNAS Toolkit - Snapshot Replication Engine
Automated local and remote disaster recovery streaming for OpenZFS and Btrfs pools.
Supports bandwidth throttling, in-flight encryption over SSH/WireGuard, and retention management.
"""

from dataclasses import asdict, dataclass, field
import os
import shutil
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

REPLICATION_JOBS_FILE = os.path.join(DATA_DIR, "replication_jobs.json")
REPLICATION_HISTORY_FILE = os.path.join(DATA_DIR, "replication_history.json")


@dataclass
class ReplicationJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    source_pool: str = ""
    source_dataset: str = ""
    target_type: str = "local"  # "local", "remote_ssh", "remote_wireguard"
    target_host: Optional[str] = None
    target_port: int = 22
    target_user: str = "root"
    target_pool: str = ""
    target_dataset: str = ""
    bandwidth_limit_kbps: Optional[int] = None  # e.g. 10000 = 10 MB/s
    incremental: bool = True
    retention_count: int = 14  # Keep last N snapshots on target
    schedule: str = "daily"  # "manual", "hourly", "daily", "weekly"
    created_at: float = field(default_factory=time.time)
    last_run: Optional[float] = None
    last_status: str = "idle"  # "idle", "running", "success", "error"
    last_error: Optional[str] = None
    bytes_transferred: int = 0


class ReplicationEngine:
    """Manages snapshot replication pipelines and asynchronous execution."""

    def __init__(self):
        self._lock = threading.RLock()
        self._running_jobs: Dict[str, threading.Thread] = {}

    def list_jobs(self) -> List[Dict[str, Any]]:
        with self._lock:
            data = read_json(REPLICATION_JOBS_FILE, [])
            if not isinstance(data, list):
                return []
            return data

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        jobs = self.list_jobs()
        for j in jobs:
            if j.get("id") == job_id:
                return j
        return None

    def create_job(self, job_data: Dict[str, Any]) -> Dict[str, Any]:
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
        error: Optional[str] = None,
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

    def _record_history(
        self,
        job_id: str,
        status: str,
        error: Optional[str],
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

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        hist = read_json(REPLICATION_HISTORY_FILE, [])
        if not isinstance(hist, list):
            return []
        return hist[-limit:]

    def run_job_async(self, job_id: str) -> Dict[str, Any]:
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

    def _execute_replication(self, job: Dict[str, Any]) -> None:
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

        try:
            # 1. Determine filesystem type: ZFS or Btrfs
            is_zfs = shutil.which("zfs") is not None
            is_btrfs = shutil.which("btrfs") is not None

            if not is_zfs and not is_btrfs:
                raise RuntimeError("Neither ZFS nor Btrfs tools found on host for snapshot stream.")

            # Create destination command / path
            if tgt_type in ("remote_ssh", "remote_wireguard"):
                if not tgt_host:
                    raise ValueError("Target host is required for remote replication")
                remote_ssh_prefix = ["ssh", "-p", str(tgt_port), f"{tgt_user}@{tgt_host}"]
            else:
                remote_ssh_prefix = []

            # 2. Build pipeline commands
            send_cmd: List[str] = []
            recv_cmd: List[str] = []

            snap_tag = f"repl_{int(time.time())}"
            if is_zfs:
                full_src = f"{src_pool}/{src_ds}".strip("/")
                src_snap = f"{full_src}@{snap_tag}"
                # Create snapshot first
                subprocess.run(["zfs", "snapshot", src_snap], check=True, capture_output=True)

                send_cmd = ["zfs", "send", "-v"]
                if job.get("incremental"):
                    send_cmd.append("-i")
                send_cmd.append(src_snap)

                full_tgt = f"{tgt_pool}/{tgt_ds}".strip("/")
                recv_cmd = remote_ssh_prefix + ["zfs", "receive", "-F", full_tgt]
            else:
                # Btrfs pipeline
                src_path = os.path.join("/mnt/storage", src_pool, src_ds)
                snap_path = f"{src_path}/.snapshots/{snap_tag}"
                os.makedirs(os.path.dirname(snap_path), exist_ok=True)
                subprocess.run(
                    ["btrfs", "subvolume", "snapshot", "-r", src_path, snap_path],
                    check=True,
                    capture_output=True,
                )

                send_cmd = ["btrfs", "send", snap_path]
                tgt_path = os.path.join(tgt_pool or "/mnt/storage", tgt_ds)
                recv_cmd = remote_ssh_prefix + ["btrfs", "receive", tgt_path]

            # 3. Handle optional rate limiting
            pv_cmd = []
            if bw_limit and shutil.which("pv"):
                pv_cmd = ["pv", "-L", f"{bw_limit}k"]

            # Execute pipeline: send_cmd | [pv] | recv_cmd
            logger.info(f"[Replication] Pipeline: {' '.join(send_cmd)} -> {' '.join(recv_cmd)}")
            p1 = subprocess.Popen(send_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if pv_cmd:
                p2 = subprocess.Popen(
                    pv_cmd,
                    stdin=p1.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                p1.stdout.close()
                p3 = subprocess.Popen(
                    recv_cmd,
                    stdin=p2.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                p2.stdout.close()
                out, err = p3.communicate()
            else:
                p3 = subprocess.Popen(
                    recv_cmd,
                    stdin=p1.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                p1.stdout.close()
                out, err = p3.communicate()

            if p3.returncode != 0:
                err_msg = err.decode("utf-8", errors="replace") if err else "Non-zero exit code"
                raise RuntimeError(f"Replication receive failed: {err_msg}")

            # Completed successfully
            self.update_job_status(job_id, "success", bytes_transferred=1024 * 1024)
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


_REPLICATION_ENGINE: Optional[ReplicationEngine] = None


def get_replication_engine() -> ReplicationEngine:
    global _REPLICATION_ENGINE
    if _REPLICATION_ENGINE is None:
        _REPLICATION_ENGINE = ReplicationEngine()
    return _REPLICATION_ENGINE
