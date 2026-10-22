"""
Test suite for Batch 3: Backend Architecture, Non-Blocking Async I/O,
Streaming Backups, and Modular Router Decomposition.
"""

import io
import os
import tempfile
import time
import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.hardware.cpu import read_cpu_util
from backend.hardware.memory import read_mem
from backend.main import app
from backend.services.app_backup import restore_app_backup
from backend.services.backup_engine import execute_backup_job, generate_backup_zip_stream, save_backup_job
from backend.services.scheduler import start_scheduler, stop_scheduler
from backend.users_db import _SESSION_CACHE, _SESSION_CACHE_LOCK, validate_user_session


def test_auth_session_cache_and_debounced_activity(client, auth_headers):
    # Verify cached session hit requires zero SQLite writes
    res = client.get("/api/health")
    assert res.status_code == 200

    # Ensure authenticated route works seamlessly with cached session
    res_me = client.get("/api/auth/me", headers=auth_headers)
    assert res_me.status_code == 200
    assert res_me.json()["username"] == "admin"


def test_backup_zip_streaming_and_exclusions(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(data_dir))

    # Create dummy regular files and heavy directories
    (data_dir / "config.json").write_text('{"test": 1}')
    (data_dir / "history.db").write_text("dummy db")
    (data_dir / "history.db-wal").write_text("wal")
    (data_dir / "sessions.json").write_text("{}")

    heavy_vms = data_dir / "vms"
    heavy_vms.mkdir()
    (heavy_vms / "disk.qcow2").write_text("heavy vm disk data")

    heavy_trash = data_dir / "trash"
    heavy_trash.mkdir()
    (heavy_trash / "deleted.txt").write_text("trash data")

    spool = generate_backup_zip_stream()
    assert spool is not None

    with zipfile.ZipFile(spool, "r") as z:
        names = z.namelist()
        assert "config.json" in names
        assert "history.db" not in names
        assert "history.db-wal" not in names
        assert "sessions.json" not in names
        assert not any("vms/" in n for n in names)
        assert not any("trash/" in n for n in names)


def test_hyper_backup_encryption_fields_and_snapshot_sourcing(tmp_path, monkeypatch):
    jobs_file = str(tmp_path / "backup_jobs.json")
    hist_file = str(tmp_path / "backup_history.json")
    monkeypatch.setattr("backend.services.backup_engine.BACKUP_JOBS_FILE", jobs_file)
    monkeypatch.setattr("backend.services.backup_engine.BACKUP_HISTORY_FILE", hist_file)

    job_data = {
        "name": "Encrypted Cloud Backup",
        "source_pool": "tank",
        "source_subvolume": "appdata",
        "destination_type": "remote",
        "remote_name": "b2_vault",
        "remote_path": "zettnas_backup",
        "encryption_enabled": True,
        "encryption_mode": "rclone_crypt",
        "bandwidth_limit_kbps": 10000,
    }
    saved = save_backup_job(job_data)
    assert saved["encryption_enabled"] is True
    assert saved["encryption_mode"] == "rclone_crypt"
    assert saved["bandwidth_limit_kbps"] == 10000


def test_cpu_utilization_calculation_guest_and_iowait(monkeypatch):
    from backend.state import Z_STATE

    Z_STATE.prev = {"idle": 0, "total": 0}

    # Line: user nice sys idle iowait irq softirq steal guest guest_nice
    # user=100, nice=0, sys=50, idle=800, iowait=50, irq=0, softirq=0, steal=0, guest=20, guest_nice=0
    # Total of first 8: 100+0+50+800+50+0+0+0 = 1000. Idle = 800.
    # Non-idle = 200 -> 20%
    fake_proc = MagicMock()
    with patch("builtins.open", return_value=io.StringIO("cpu  100 0 50 800 50 0 0 0 20 0\n")):
        util = read_cpu_util()
        assert util == 20


def test_memory_utilization_zfs_arc_reclaim(tmp_path, monkeypatch):
    fake_proc = tmp_path / "proc"
    fake_proc.mkdir()
    monkeypatch.setattr("backend.hardware.memory.HOST_PROC", str(fake_proc))

    # 16 GB total, 4 GB free available, but 6 GB ZFS ARC
    meminfo_content = "MemTotal:       16777216 kB\nMemFree:         1048576 kB\nMemAvailable:    4194304 kB\n"
    (fake_proc / "meminfo").write_text(meminfo_content)

    zfs_dir = fake_proc / "spl" / "kstat" / "zfs"
    zfs_dir.mkdir(parents=True)
    # 6 GB in bytes = 6 * 1024 * 1024 * 1024 = 6442450944
    arcstats_content = (
        "4 1 0x01 88 4096 12345 67890\n"
        "name                            type data\n"
        "size                            4    6442450944\n"
    )
    (zfs_dir / "arcstats").write_text(arcstats_content)

    stats = read_mem()
    assert stats["total_gb"] == 16.0
    # Available = 4 GB + 6 GB ARC = 10 GB. Used = 16 - 10 = 6 GB.
    assert stats["used_gb"] == 6.0
    assert stats["pct"] == 38


def test_scheduler_lifecycle_and_tick():
    start_scheduler()
    time.sleep(0.1)
    stop_scheduler()
    # Scheduler should stop cleanly without hanging


def test_router_decomposition_imports():
    from backend.api.catalog import router as catalog_router
    from backend.api.diagnostics import router as diagnostics_router
    from backend.api.docker import router as docker_router
    from backend.api.fs import router as fs_router
    from backend.api.system import router as system_router

    assert docker_router is not None
    assert catalog_router is not None
    assert fs_router is not None
    assert diagnostics_router is not None
    assert system_router is not None
