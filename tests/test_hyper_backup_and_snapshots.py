"""
Unit and Integration Tests for Batch 4:
Hyper-Backup Orchestrator, Snapshot Rotation, Point-in-Time Revert,
and Background Scheduler.
"""

import os
import shutil
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    UnraidStorageAdapter,
    PlatformCapabilityError,
)
from backend.services.backup_engine import (
    get_backup_jobs,
    save_backup_job,
    delete_backup_job,
    get_backup_history,
    prune_job_snapshots,
    execute_backup_job,
    start_backup_scheduler,
    stop_backup_scheduler,
)


@pytest.fixture(autouse=True)
def isolated_hyper_backup_env(monkeypatch, tmp_path):
    """Isolates data directories and storage pools into temporary paths."""
    test_storage = tmp_path / "storage"
    test_storage.mkdir()
    test_data = tmp_path / "data"
    test_data.mkdir()

    jobs_file = str(test_data / "backup_jobs.json")
    history_file = str(test_data / "backup_history.json")

    monkeypatch.setattr("backend.config.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.backup_engine.BACKUP_JOBS_FILE", jobs_file)
    monkeypatch.setattr("backend.services.backup_engine.BACKUP_HISTORY_FILE", history_file)
    monkeypatch.setattr("backend.hardware.pal_storage.POOL_PATH", str(test_storage))

    # Reset platform adapter singleton
    monkeypatch.setattr("backend.hardware.pal_storage._CACHED_ADAPTER", None)

    yield


@pytest.fixture
def auth_client(monkeypatch):
    """Provides a TestClient with bypassed authentication."""
    monkeypatch.setattr("backend.auth.require_scope", lambda *scopes: lambda: None)
    return TestClient(app)


# =========================================================================
# 1. Storage Platform Adapter: restore_snapshot
# =========================================================================


def test_unraid_storage_adapter_rejects_restore_snapshot():
    adapter = UnraidStorageAdapter()
    with pytest.raises(PlatformCapabilityError) as exc_info:
        adapter.restore_snapshot("unraid_array", "snap_20261009", "shares")
    assert "observer mode" in str(exc_info.value).lower()


def test_generic_linux_storage_adapter_restore_snapshot(tmp_path, monkeypatch):
    storage_dir = tmp_path / "storage"
    adapter = GenericLinuxStorageAdapter(pool_path=str(storage_dir))

    # Snapshot doesn't exist
    res = adapter.restore_snapshot("default", "nonexistent_snap", "data")
    assert res["status"] == "error"
    assert "not found" in res["message"]

    # Create dummy snapshot
    snaps_dir = storage_dir / "@snapshots"
    snaps_dir.mkdir(parents=True)
    snap_target = snaps_dir / "data_snap1"
    snap_target.mkdir()

    # Pre-existing active subvolume
    shares_dir = storage_dir / "@shares"
    shares_dir.mkdir(parents=True)
    active_subvol = shares_dir / "data"
    active_subvol.mkdir()

    # Mock _run_cmd so btrfs command simulates success
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (0, "snapshot created", ""))

    restore_res = adapter.restore_snapshot("default", "data_snap1", "data")
    assert restore_res["status"] == "restored"
    assert restore_res["archived_previous"] is not None
    assert "pre_restore" in restore_res["archived_previous"]


# =========================================================================
# 2. Hyper-Backup Engine: CRUD & Scheduling
# =========================================================================


def test_backup_jobs_crud():
    assert get_backup_jobs() == []

    job_data = {
        "name": "Daily Photo Sync",
        "source_pool": "default",
        "source_subvolume": "photos",
        "destination_type": "remote",
        "remote_name": "b2-vault",
        "remote_path": "photos-backup",
        "schedule": "daily",
        "retention_count": 5,
        "enabled": True,
    }
    saved = save_backup_job(job_data)
    assert saved["id"] is not None
    assert saved["name"] == "Daily Photo Sync"
    assert saved["retention_count"] == 5

    # Retrieve list
    jobs = get_backup_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == saved["id"]

    # Update job
    saved["schedule"] = "hourly"
    saved["retention_count"] = 10
    updated = save_backup_job(saved)
    assert updated["schedule"] == "hourly"
    assert updated["retention_count"] == 10

    # Delete job
    assert delete_backup_job(saved["id"]) is True
    assert get_backup_jobs() == []
    assert delete_backup_job("nonexistent") is False


# =========================================================================
# 3. Snapshot Retention Pruning
# =========================================================================


def test_prune_job_snapshots(monkeypatch):
    class MockPlatform:
        def __init__(self):
            self.deleted = []

        def list_snapshots(self, pool_id):
            return [
                {"name": "photos_20261001_000000", "created_at": 100},
                {"name": "photos_20261002_000000", "created_at": 200},
                {"name": "photos_20261003_000000", "created_at": 300},
                {"name": "photos_20261004_000000", "created_at": 400},
                {"name": "photos_20261005_000000", "created_at": 500},
                {"name": "documents_20261005_000000", "created_at": 550},
            ]

        def delete_snapshot(self, pool_id, snap_name):
            self.deleted.append(snap_name)
            return {"status": "deleted"}

    mock_pal = MockPlatform()
    monkeypatch.setattr("backend.services.backup_engine.get_storage_platform", lambda: mock_pal)

    # Retention count of 3 should delete the 2 oldest photos snapshots
    pruned = prune_job_snapshots("default", "photos", retention_count=3)
    assert pruned == ["photos_20261001_000000", "photos_20261002_000000"]
    assert mock_pal.deleted == ["photos_20261001_000000", "photos_20261002_000000"]


# =========================================================================
# 4. Job Execution & Pipeline
# =========================================================================


def test_execute_backup_job_local_and_remote(monkeypatch):
    class MockPlatform:
        def get_pool_path(self, pool_id):
            return "/tmp/storage"

        def create_snapshot(self, pool_id, subvol_name, snapshot_name, readonly):
            return {"status": "created", "snapshot": snapshot_name}

        def list_snapshots(self, pool_id):
            return []

        def delete_snapshot(self, pool_id, snap_name):
            return {"status": "deleted"}

    class MockRclone:
        def start_sync_job(self, src, dst, action):
            return {"id": "sync-1234", "status": "running"}

    monkeypatch.setattr("backend.services.backup_engine.get_storage_platform", lambda: MockPlatform())
    monkeypatch.setattr("backend.services.backup_engine.get_rclone_engine", lambda: MockRclone())

    job = save_backup_job(
        {
            "name": "Cloud Backup Pipeline",
            "source_pool": "default",
            "source_subvolume": "vault",
            "destination_type": "remote",
            "remote_name": "s3-aws",
            "remote_path": "zettnas-backups/vault",
            "schedule": "daily",
            "retention_count": 7,
        }
    )

    result = execute_backup_job(job["id"])
    assert result["status"] == "success"
    assert result["snapshot_name"].startswith("vault_")
    assert result["rclone_job_id"] == "sync-1234"

    # Verify history recorded
    history = get_backup_history()
    assert len(history) == 1
    assert history[0]["job_id"] == job["id"]
    assert history[0]["status"] == "success"

    # Verify updated job status
    jobs = get_backup_jobs()
    assert jobs[0]["last_status"] == "success"
    assert jobs[0]["last_run_at"] is not None


def test_scheduler_lifecycle():
    start_backup_scheduler()
    # Call again to test idempotency
    start_backup_scheduler()
    stop_backup_scheduler()


# =========================================================================
# 5. REST Endpoints (TestClient)
# =========================================================================


def test_api_backup_schedule_endpoints(client, auth_headers, monkeypatch):
    # 1. List empty schedule
    res = client.get("/api/backup/schedule", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["jobs"] == []

    # 2. Create job
    payload = {
        "name": "Integration Test Pipeline",
        "source_pool": "default",
        "source_subvolume": "media",
        "destination_type": "local_snapshot",
        "schedule": "daily",
        "retention_count": 3,
        "enabled": True,
    }
    res = client.post("/api/backup/schedule", json=payload, headers=auth_headers)
    assert res.status_code == 200
    job = res.json()["job"]
    job_id = job["id"]
    assert job["name"] == "Integration Test Pipeline"

    # 3. Run job
    monkeypatch.setattr(
        "backend.api.backup.execute_backup_job",
        lambda jid: {"id": "hist-1", "job_id": jid, "status": "success"},
    )
    run_res = client.post(f"/api/backup/schedule/{job_id}/run", headers=auth_headers)
    assert run_res.status_code == 200
    assert run_res.json()["result"]["status"] == "success"

    # 4. History
    hist_res = client.get("/api/backup/history", headers=auth_headers)
    assert hist_res.status_code == 200

    # 5. Delete job
    del_res = client.delete(f"/api/backup/schedule/{job_id}", headers=auth_headers)
    assert del_res.status_code == 200


def test_api_snapshots_endpoints(client, auth_headers, monkeypatch):
    class MockPlatform:
        def list_snapshots(self, pool_id):
            return [{"name": "snap1", "path": "/snaps/snap1", "created_at": 1000}]

        def create_snapshot(self, pool_id, subvol_name, snapshot_name, readonly):
            return {"status": "created", "snapshot": snapshot_name}

        def restore_snapshot(self, pool_id, snapshot_name, target_subvol=""):
            return {"status": "restored", "snapshot": snapshot_name}

        def delete_snapshot(self, pool_id, snapshot_name):
            return {"status": "deleted", "snapshot": snapshot_name}

    monkeypatch.setattr("backend.api.backup.get_storage_platform", lambda: MockPlatform())

    # List snapshots
    res = client.get("/api/backup/snapshots?pool_id=default", headers=auth_headers)
    assert res.status_code == 200
    assert len(res.json()["snapshots"]) == 1

    # Create snapshot
    c_res = client.post(
        "/api/backup/snapshots", json={"pool_id": "default", "subvol_name": "data"}, headers=auth_headers
    )
    assert c_res.status_code == 200
    assert c_res.json()["result"]["status"] == "created"

    # Restore snapshot
    r_res = client.post(
        "/api/backup/restore-snapshot", json={"pool_id": "default", "snapshot_name": "snap1"}, headers=auth_headers
    )
    assert r_res.status_code == 200
    assert r_res.json()["result"]["status"] == "restored"

    # Delete snapshot
    d_res = client.delete("/api/backup/snapshots/default/snap1", headers=auth_headers)
    assert d_res.status_code == 200
    assert d_res.json()["result"]["status"] == "deleted"
