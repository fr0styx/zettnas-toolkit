"""B12b (REL-9, decision 8): one backup engine for folders. Copy jobs that exist keep a version of
every file they replace, skip a run while writes are frozen and can be moved to an off-site
(restic) backup; no new copy job to a cloud remote is made; a settings upload counts only once
it is there."""

from types import SimpleNamespace

import pytest

from backend import config
from backend.services import backup_engine as be
from backend.services import offsite_backup as ob
from backend.services.backup_migration import migrate_to_offsite


class Rclone:
    def __init__(self, status="success"):
        self.syncs, self.purged, self.status = [], [], status
        self.dirs = {}

    def start_sync_job(self, **kw):
        self.syncs.append(kw)
        return {"id": f"s{len(self.syncs)}"}

    def get_sync_job(self, job_id):
        return {"status": self.status, "error": "quota exceeded" if self.status != "success" else None}

    def create_crypt_remote(self, **kw):
        return None

    def list_dirs(self, location):
        return self.dirs.get(location, [])

    def purge(self, location):
        self.purged.append(location)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    (pool / "photos").mkdir(parents=True)
    (pool / "photos" / "a.jpg").write_text("x")
    rclone = Rclone()
    pal = SimpleNamespace(create_snapshot=lambda **k: {}, get_pool_path=lambda p: str(pool))
    monkeypatch.setattr(be, "get_storage_platform", lambda: pal)
    monkeypatch.setattr(be, "prune_job_snapshots", lambda *a: [])
    monkeypatch.setattr(be, "get_rclone_engine", lambda: rclone)
    monkeypatch.setattr(be, "BACKUP_JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(be, "BACKUP_HISTORY_FILE", str(tmp_path / "history.json"), raising=False)
    monkeypatch.setattr(be, "_writes_frozen", lambda: False)
    monkeypatch.setattr("backend.services.backup_hooks.run_dumps", lambda paths: [])
    job = be.save_backup_job(
        {
            "name": "Photos",
            "source_subvolume": "photos",
            "remote_name": "cloud",
            "remote_path": "nas",
            "retention_count": 2,
        }
    )
    return SimpleNamespace(pool=pool, rclone=rclone, job=job, tmp=tmp_path)


def test_a_copy_keeps_what_it_replaces_as_a_version(engine):
    engine.rclone.dirs["cloud:nas/.zettnas-versions"] = ["20261025-0200", "20261026-0200", "20261027-0200"]
    rec = be.execute_backup_job(engine.job["id"])
    flags = engine.rclone.syncs[0]["extra_flags"]
    backup_dir = flags[flags.index("--backup-dir") + 1]
    assert (
        backup_dir.startswith("cloud:nas/.zettnas-versions/")
        and flags[flags.index("--exclude") + 1] == "/.zettnas-versions/**"
    )
    assert rec["status"] == "success" and engine.rclone.purged == ["cloud:nas/.zettnas-versions/20261025-0200"]


def test_versions_live_inside_an_encrypted_copy_too():
    assert be._versions_of("crypt_ab12:") == "crypt_ab12:.zettnas-versions"
    assert be._versions_of("cloud:nas/") == "cloud:nas/.zettnas-versions"


def test_pruning_versions_that_fails_leaves_the_backup_done(engine):
    def broken(location):
        raise RuntimeError("remote offline")

    engine.rclone.list_dirs = broken
    assert be.execute_backup_job(engine.job["id"])["status"] == "success"


def test_a_copy_skips_while_writes_are_frozen(engine, monkeypatch):
    monkeypatch.setattr(be, "_writes_frozen", lambda: True)
    rec = be.execute_backup_job(engine.job["id"])
    assert rec["status"] == "skipped" and not engine.rclone.syncs
    job = next(j for j in be.get_backup_jobs() if j["id"] == engine.job["id"])
    assert job["last_status"] == "skipped" and "ransomware guard" in job["last_error"]


def test_the_frozen_check_reads_the_guard(monkeypatch):
    from backend.services import ransomware_guard

    monkeypatch.setattr(ransomware_guard, "get_guard", lambda: SimpleNamespace(frozen=True))
    assert be._writes_frozen() is True

    def broken():
        raise RuntimeError("no state")

    monkeypatch.setattr(ransomware_guard, "get_guard", broken)
    assert be._writes_frozen() is False


def test_a_settings_upload_counts_only_once_it_is_there(engine, monkeypatch):
    monkeypatch.setattr(
        be, "generate_backup_zip_stream", lambda passphrase: SimpleNamespace(read=lambda: b"zip", close=lambda: None)
    )
    monkeypatch.setattr(be, "DATA_DIR", str(engine.tmp))
    job = {
        "kind": "config",
        "remote_name": "cloud",
        "remote_path": "settings",
        "encryption_password": be._seal_passphrase("correct-horse"),
    }
    assert be._export_settings(job, 2).startswith("cloud:settings/")
    engine.rclone.status = "error"
    with pytest.raises(ValueError, match="did not reach cloud: quota exceeded"):
        be._export_settings(job, 2)


def test_no_new_copy_job_to_a_cloud_remote(client, auth_headers, engine):
    body = {"name": "New", "source_subvolume": "photos", "remote_name": "cloud", "remote_path": "x"}
    res = client.post("/api/backup/schedule", json=body, headers=auth_headers)
    assert res.status_code == 409 and "off-site backup" in res.json()["detail"]
    edit = {**body, "id": engine.job["id"], "name": "Photos renamed"}
    assert client.post("/api/backup/schedule", json=edit, headers=auth_headers).status_code == 200
    snap = {"name": "Snap", "source_subvolume": "photos", "destination_type": "local_snapshot"}
    assert client.post("/api/backup/schedule", json=snap, headers=auth_headers).status_code == 200


@pytest.fixture
def offsite(engine, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(engine.pool)])
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "KEY_DIR", str(tmp_path / "keys"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    inits = []
    monkeypatch.setattr(ob, "init", lambda repo_id: inits.append(repo_id) or ob._update(repo_id, initialized=True))
    return inits


def test_a_copy_job_moves_to_an_offsite_backup(engine, offsite):
    res = migrate_to_offsite(engine.job["id"])
    repo = res["repo"]
    assert repo["location"] == "rclone:cloud:nas-restic" and repo["paths"] == [str(engine.pool / "photos")]
    assert repo["keep"]["daily"] == 7 and repo["hour"] == 2 and offsite == [repo["id"]]
    job = next(j for j in be.get_backup_jobs() if j["id"] == engine.job["id"])
    assert job["enabled"] is False and job["migrated_to"] == repo["id"]


def test_only_a_cloud_copy_of_a_folder_can_move(engine, offsite):
    snap = be.save_backup_job({"name": "Snap", "source_subvolume": "photos", "destination_type": "local_snapshot"})
    with pytest.raises(ValueError):
        migrate_to_offsite(snap["id"])
    with pytest.raises(KeyError):
        migrate_to_offsite("nope")


def test_the_move_route(client, auth_headers, engine, offsite, monkeypatch):
    res = client.post(f"/api/backup/schedule/{engine.job['id']}/migrate", headers=auth_headers)
    assert res.status_code == 200 and res.json()["status"] == "migrated"
    assert client.post("/api/backup/schedule/nope/migrate", headers=auth_headers).status_code == 404

    def unreachable(job_id):
        raise ob.ResticError("Fatal: unable to open the repository")

    monkeypatch.setattr("backend.services.backup_migration.migrate_to_offsite", unreachable)
    assert client.post(f"/api/backup/schedule/{engine.job['id']}/migrate", headers=auth_headers).status_code == 502

    def wrong(job_id):
        raise ValueError("Only a copy of a folder to a cloud remote can be moved")

    monkeypatch.setattr("backend.services.backup_migration.migrate_to_offsite", wrong)
    assert client.post(f"/api/backup/schedule/{engine.job['id']}/migrate", headers=auth_headers).status_code == 400


def test_offsite_backups_keep_every_version_while_frozen(tmp_path, monkeypatch):
    from backend.services import ransomware_guard

    storage = tmp_path / "storage"
    (storage / "family").mkdir(parents=True)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(storage)])
    monkeypatch.setattr(ob, "REPOS_FILE", str(tmp_path / "repos.json"))
    monkeypatch.setattr(ob, "DATA_DIR", str(tmp_path))
    ob.save_repo("usb", "USB", str(storage / "usb"), [str(storage / "family")], hour=None)
    ob._update("usb", initialized=True)
    restic = []
    monkeypatch.setattr("backend.services.backup_hooks.run_dumps", lambda paths: [])
    monkeypatch.setattr(ob, "_unlock", lambda repo: None)
    monkeypatch.setattr(ob, "_run", lambda repo, args, **kw: (0, ""))
    monkeypatch.setattr(ob, "run_restic", lambda repo, args, **kw: restic.append(args[0]) or "")
    monkeypatch.setattr(ransomware_guard, "get_guard", lambda: SimpleNamespace(frozen=True))
    ob.backup("usb")
    assert "forget" not in restic
    monkeypatch.setattr(ransomware_guard, "get_guard", lambda: SimpleNamespace(frozen=False))
    ob.backup("usb")
    assert restic == ["forget"]


def test_rclone_lists_and_purges_folders(monkeypatch):
    from backend.services import rclone_engine

    engine = rclone_engine.RcloneEngine.__new__(rclone_engine.RcloneEngine)
    engine.config_file = "/tmp/rclone.conf"
    monkeypatch.setattr(engine, "_get_rclone_bin", lambda: "rclone")
    runs = []

    def fake_run(cmd, capture_output, text, timeout):
        runs.append(cmd)
        if cmd[1] == "lsf" and "missing" in cmd[-1]:
            return SimpleNamespace(returncode=3, stdout="", stderr="directory not found")
        if cmd[1] == "purge" and "locked" in cmd[-1]:
            return SimpleNamespace(returncode=1, stdout="", stderr="permission denied")
        return SimpleNamespace(returncode=0, stdout="20261026-0200/\n20261027-0200/\n", stderr="")

    monkeypatch.setattr(rclone_engine.subprocess, "run", fake_run)
    assert engine.list_dirs("cloud:nas/.zettnas-versions") == ["20261026-0200", "20261027-0200"]
    assert runs[0][:4] == ["rclone", "lsf", "--config", "/tmp/rclone.conf"]
    assert engine.list_dirs("cloud:missing") == []
    engine.purge("cloud:nas/.zettnas-versions/20261026-0200")
    with pytest.raises(RuntimeError, match="permission denied"):
        engine.purge("cloud:locked")
