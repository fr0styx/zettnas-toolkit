"""Scheduled, encrypted ZettNAS settings backups to a pool folder or a remote (OPS-8)."""

import io
import zipfile

import pytest

from backend import config
from backend.services import backup_engine as be


@pytest.fixture
def env(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    pool.mkdir()
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(be, "BACKUP_JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(be, "record_backup_history", lambda rec: None)
    return pool


def _job(pool, **kw):
    base = {
        "name": "settings",
        "kind": "config",
        "destination_type": "local_folder",
        "local_path": str(pool / "zettnas"),
        "encryption_password": "correct-horse",
        "retention_count": 2,
    }
    return {**base, **kw}


def test_settings_jobs_need_a_passphrase_and_a_folder_in_the_pool(env, tmp_path):
    with pytest.raises(ValueError, match="passphrase"):
        be.save_backup_job(_job(env, encryption_password="short"))
    with pytest.raises(ValueError, match="inside the storage folders"):
        be.save_backup_job(_job(env, local_path=str(tmp_path / "elsewhere")))
    saved = be.save_backup_job(_job(env))
    assert saved["kind"] == "config" and saved["encrypted"] and saved["source_subvolume"] == ""
    # editing without retyping the passphrase keeps it
    again = be.save_backup_job({**_job(env), "id": saved["id"], "encryption_password": None})
    assert be.job_passphrase(again) == "correct-horse"  # stored encrypted


def test_runs_write_encrypted_copies_and_keep_the_newest(env, monkeypatch):
    job = be.save_backup_job(_job(env))
    n = {"i": 0}

    def stamp(fmt, *a):
        n["i"] += 1
        return f"20261024_{n['i']:06d}"

    monkeypatch.setattr(be.time, "strftime", stamp)
    names = []
    for _ in range(3):
        rec = be.execute_backup_job(job["id"])
        assert rec["status"] == "success", rec.get("error")
        names.append(rec["snapshot_name"].rsplit("/", 1)[1])
    files = sorted(p.name for p in (env / "zettnas").iterdir())
    assert files == names[1:]  # the newest two (retention 2)
    blob = (env / "zettnas" / files[-1]).read_bytes()
    with pytest.raises(ValueError):
        be.decrypt_backup(blob, "wrong-passphrase")
    with zipfile.ZipFile(io.BytesIO(be.decrypt_backup(blob, "correct-horse"))) as z:
        assert be.MANIFEST_NAME in z.namelist()


def test_job_list_never_returns_passphrases(client, auth_headers, env):
    be.save_backup_job(_job(env))
    jobs = client.get("/api/backup/schedule", headers=auth_headers).json()["jobs"]
    assert jobs and all(j["encryption_password"] is None and j["has_passphrase"] for j in jobs)


def test_data_jobs_keep_their_encryption_settings(env):
    saved = be.save_backup_job(
        {
            "name": "photos",
            "source_subvolume": "photos",
            "remote_name": "b2",
            "encrypted": True,
            "encryption_password": "crypt-pass-1",
        }
    )
    assert saved["encrypted"] and be.job_passphrase(saved) == "crypt-pass-1"
