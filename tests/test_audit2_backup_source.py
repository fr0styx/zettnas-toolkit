"""Backup job sources stay inside the pool (audit pass 2)."""

from types import SimpleNamespace

import pytest


@pytest.fixture
def engine(tmp_path, monkeypatch):
    from backend.services import backup_engine

    pool = tmp_path / "pool"
    (pool / "photos").mkdir(parents=True)
    calls = []
    pal = SimpleNamespace(create_snapshot=lambda **k: {}, get_pool_path=lambda p: str(pool))
    sync = SimpleNamespace(
        start_sync_job=lambda **k: calls.append(k) or {"id": "j"}, create_crypt_remote=lambda **k: None
    )
    monkeypatch.setattr(backup_engine, "get_storage_platform", lambda: pal)
    monkeypatch.setattr(backup_engine, "prune_job_snapshots", lambda *a: [])
    monkeypatch.setattr(backup_engine, "get_rclone_engine", lambda: sync)
    monkeypatch.setattr(backup_engine, "BACKUP_JOBS_FILE", str(tmp_path / "jobs.json"))
    return backup_engine, pool, calls


@pytest.mark.parametrize("bad", ["/", "/etc", "../outside", "photos/../../x", "a\\b"])
def test_sources_outside_the_pool_are_refused(engine, bad):
    backup_engine, _, _ = engine
    with pytest.raises(ValueError):
        backup_engine.save_backup_job({"name": "t", "source_subvolume": bad, "remote_name": "r"})


def test_a_pool_folder_is_synced(engine):
    backup_engine, pool, calls = engine
    job = backup_engine.save_backup_job(
        {"name": "t", "source_subvolume": "photos", "remote_name": "r", "remote_path": "x"}
    )
    backup_engine.execute_backup_job(job["id"])
    assert calls and calls[0]["src"] == str(pool / "photos")


def test_schedule_route_answers_400(client, auth_headers):
    r = client.post("/api/backup/schedule", headers=auth_headers, json={"name": "t", "source_subvolume": "/etc"})
    assert r.status_code == 400
