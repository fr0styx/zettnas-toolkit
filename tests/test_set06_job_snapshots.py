"""SET-06, the owner's decision S18: a backup job fails when no snapshot was made.

The storage layer answers {"status": "error"} where it cannot make a snapshot, and no caller read
it: a job that only makes snapshots ended "Done" with nothing made, and "Take a snapshot" said it
worked. Job snapshots also get a name with the folder before "@", so the safe rollback and the
right restore target apply, and a job prunes only its own."""

import pytest

from backend.hardware.pal_storage import PlatformCapabilityError
from backend.services import backup_engine
from backend.services.backup_engine import (
    execute_backup_job,
    get_backup_history,
    get_backup_jobs,
    job_snapshot_name,
    made_by_a_job,
    prune_job_snapshots,
    save_backup_job,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr("backend.config.DATA_DIR", str(data))
    monkeypatch.setattr("backend.services.backup_engine.DATA_DIR", str(data))
    monkeypatch.setattr("backend.services.backup_engine.BACKUP_JOBS_FILE", str(data / "backup_jobs.json"))
    monkeypatch.setattr("backend.services.backup_engine.BACKUP_HISTORY_FILE", str(data / "backup_history.json"))
    monkeypatch.setattr("backend.services.backup_engine._dump_databases", lambda pal, pool_id, subvol: [])


class Storage:
    """A storage layer whose create_snapshot() answers what the test says."""

    def __init__(self, answer):
        self.answer = answer
        self.made, self.deleted = [], []
        self.existing = []

    def get_pool_path(self, pool_id):
        return "/tmp/storage"

    def create_snapshot(self, pool_id, subvol_name, snapshot_name, readonly):
        if isinstance(self.answer, Exception):
            raise self.answer
        self.made.append(snapshot_name)
        return dict(self.answer)

    def list_snapshots(self, pool_id):
        return list(self.existing)

    def delete_snapshot(self, pool_id, snapshot_name):
        self.deleted.append(snapshot_name)
        return {"status": "deleted"}


def _job(dest="local_snapshot", **extra):
    return save_backup_job(
        {
            "name": "Photos, every night",
            "source_pool": "default",
            "source_subvolume": "photos",
            "destination_type": dest,
            "schedule": "daily",
            "retention_count": 7,
            **extra,
        }
    )


@pytest.mark.parametrize(
    "answer, why",
    [
        ({"status": "error", "code": 1, "output": "ERROR: not a btrfs subvolume: /mnt/pool/photos"}, "not a btrfs"),
        ({"status": "error", "code": 127, "output": ""}, "did not make it"),
        (PlatformCapabilityError("Unraid keeps its own snapshots"), "keeps its own snapshots"),
    ],
)
def test_a_snapshot_only_job_fails_when_no_snapshot_was_made(monkeypatch, answer, why):
    monkeypatch.setattr(backup_engine, "get_storage_platform", lambda: Storage(answer))
    job = _job()
    result = execute_backup_job(job["id"])
    assert result["status"] == "error"
    assert "No snapshot of photos was made" in result["error"] and why in result["error"]
    saved = next(j for j in get_backup_jobs() if j["id"] == job["id"])
    assert saved["last_status"] == "error" and not saved.get("last_success_at")
    assert get_backup_history()[0]["status"] == "error"


def test_a_snapshot_only_job_that_made_one_is_done(monkeypatch):
    storage = Storage({"status": "created", "snapshot": "/mnt/pool/@snapshots/x"})
    monkeypatch.setattr(backup_engine, "get_storage_platform", lambda: storage)
    result = execute_backup_job(_job()["id"])
    assert result["status"] == "success"
    assert result["snapshot_name"].startswith("photos@backup-") and storage.made == [result["snapshot_name"]]


def test_a_cloud_copy_goes_on_without_the_snapshot_and_says_so(monkeypatch):
    class Rclone:
        def start_sync_job(self, src, dst, action, **kw):
            return {"id": "sync-1", "status": "running"}

        def get_sync_job(self, job_id):
            return {"id": job_id, "status": "success"}

    monkeypatch.setattr(
        backup_engine, "get_storage_platform", lambda: Storage({"status": "error", "output": "no tools"})
    )
    monkeypatch.setattr(backup_engine, "get_rclone_engine", lambda: Rclone())
    monkeypatch.setattr(backup_engine, "_source_is_empty", lambda path: False)
    result = execute_backup_job(_job("remote", remote_name="b2", remote_path="nas/photos")["id"])
    assert result["status"] == "success"
    assert result["snapshot_name"] == "skipped (no tools)"


def test_the_name_has_the_folder_before_the_at_sign():
    name = job_snapshot_name("photos")
    assert name.startswith("photos@backup-") and name.split("@", 1)[0] == "photos"
    assert job_snapshot_name("photos", backup_engine.MANUAL_TAG).startswith("photos@manual-")


@pytest.mark.parametrize(
    "name, own",
    [
        ("photos@backup-20261110-020000", True),
        ("photos_20261001_000000", True),  # the name jobs gave before
        ("photos@auto-20261110-0200", False),  # a scheduled snapshot
        ("photos@manual-20261110-120000", False),  # taken by hand
        ("photos@before-rollback-20261110-1200", False),
        ("photos_old_20261001_000000", False),  # another share
        ("photos_before_the_move", False),  # named by hand
        ("documents_20261001_000000", False),
    ],
)
def test_which_snapshots_a_job_made(name, own):
    assert made_by_a_job(name, "photos") is own


def test_a_job_prunes_only_its_own(monkeypatch):
    storage = Storage({"status": "created"})
    storage.existing = [
        {"name": "photos_20261001_000000", "created_at": 100},
        {"name": "photos_old_20260101_000000", "created_at": 50},
        {"name": "photos_before_the_move", "created_at": 60},
        {"name": "photos@auto-20261001-0000", "created_at": 110},
        {"name": "photos@backup-20261002-000000", "created_at": 200},
        {"name": "photos@backup-20261003-000000", "created_at": 300},
        {"name": "photos@manual-20261003-120000", "created_at": 310},
    ]
    monkeypatch.setattr(backup_engine, "get_storage_platform", lambda: storage)
    assert prune_job_snapshots("default", "photos", retention_count=1) == [
        "photos_20261001_000000",
        "photos@backup-20261002-000000",
    ]
    assert storage.deleted == ["photos_20261001_000000", "photos@backup-20261002-000000"]


def test_take_a_snapshot_says_when_it_did_not_work(client, auth_headers, monkeypatch):
    storage = Storage({"status": "error", "code": 1, "output": "ERROR: not a btrfs subvolume"})
    monkeypatch.setattr("backend.api.backup.get_storage_platform", lambda: storage)
    r = client.post("/api/backup/snapshots", json={"pool_id": "default", "subvol_name": "photos"}, headers=auth_headers)
    assert r.status_code == 502 and "could not be made" in r.json()["detail"] and "not a btrfs" in r.json()["detail"]
    storage.answer = {"status": "created", "snapshot": "/x"}
    r = client.post("/api/backup/snapshots", json={"pool_id": "default", "subvol_name": "photos"}, headers=auth_headers)
    assert r.status_code == 200 and storage.made[-1].startswith("photos@manual-")


def test_deleting_a_snapshot_says_when_it_did_not_work(client, auth_headers, monkeypatch):
    class Stuck(Storage):
        def delete_snapshot(self, pool_id, snapshot_name):
            return {"status": "error", "code": 1}

    monkeypatch.setattr("backend.api.backup.get_storage_platform", lambda: Stuck({}))
    r = client.delete("/api/backup/snapshots/default/photos@manual-1", headers=auth_headers)
    assert r.status_code == 502 and "could not be deleted" in r.json()["detail"]
