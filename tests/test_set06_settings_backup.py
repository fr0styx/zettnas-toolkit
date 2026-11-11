"""SET-06, the owner's decisions S17 and S19: a settings backup that waits is shown, and the
settings file is always encrypted.

An uploaded backup is only checked and staged; it is applied at the next start. Nothing showed
that one was waiting and nothing could cancel it, so it replaced people, passwords and shares at
whatever restart came next. The plain download held the keys of every off-site backup."""

import io
import os

import pytest

from backend.api import backup as backup_api
from backend.fsutil import atomic_write_json
from backend.services import backup_engine, box_restore


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_api, "DATA_DIR", str(tmp_path))
    return tmp_path


def _stage(data_dir, files=("users.db", "shares.json")):
    staged = data_dir / backup_engine.STAGED_RESTORE_DIR
    staged.mkdir()
    for name in files:
        (staged / name).write_text("from the backup")
    atomic_write_json(str(staged / backup_engine.STAGED_MANIFEST), list(files))
    return staged


def test_nothing_waits_on_an_ordinary_day(client, auth_headers, data_dir):
    assert client.get("/api/system/restore/staged", headers=auth_headers).json() == {"staged": False}
    r = client.post("/api/system/restore/apply", headers=auth_headers)
    assert r.status_code == 409


def test_a_waiting_backup_is_shown_and_can_be_discarded(client, auth_headers, data_dir):
    staged = _stage(data_dir)
    info = client.get("/api/system/restore/staged", headers=auth_headers).json()
    assert info["staged"] is True and info["files"] == 2 and info["at"] > 0
    r = client.delete("/api/system/restore/staged", headers=auth_headers)
    assert r.status_code == 200 and r.json()["discarded"] is True
    assert not staged.exists()
    assert client.get("/api/system/restore/staged", headers=auth_headers).json() == {"staged": False}
    # and the next start has nothing to apply
    assert backup_engine.apply_staged_restore(str(data_dir)) == []


def test_an_interrupted_upload_is_not_a_waiting_backup(data_dir):
    (data_dir / backup_engine.STAGED_RESTORE_DIR).mkdir()  # no list of files yet
    assert backup_engine.staged_restore_info(str(data_dir)) == {"staged": False}


@pytest.mark.real_confirmations
def test_restart_now_is_asked_and_then_restarts(client, auth_headers, data_dir, monkeypatch):
    _stage(data_dir)
    restarts = []
    monkeypatch.setattr(box_restore, "restart_to_apply", lambda: restarts.append(1) or {"restarting": True})
    r = client.post("/api/system/restore/apply", headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "system.apply_restore" and restarts == []
    token = client.post(
        "/api/confirmations", json={"action": "system.apply_restore", "target": ""}, headers=auth_headers
    ).json()["token"]
    r = client.post("/api/system/restore/apply", headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code == 200 and r.json()["restarting"] is True and restarts == [1]


def test_only_the_owner_sees_or_touches_it(client, data_dir):
    from backend.users_db import create_user, delete_user, get_user_by_username

    _stage(data_dir)
    name = "set06_storage_admin"
    if not get_user_by_username(name):
        create_user(name, name, "GoodPass123!", role_id="storage_admin")
    try:
        token = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"}).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/system/restore/staged", headers=headers).status_code == 403
        assert client.delete("/api/system/restore/staged", headers=headers).status_code == 403
        assert client.post("/api/system/restore/apply", headers=headers).status_code == 403
    finally:
        delete_user(get_user_by_username(name)["id"])
    assert (data_dir / backup_engine.STAGED_RESTORE_DIR).exists()


def test_the_settings_file_is_always_encrypted(client, auth_headers, monkeypatch):
    made = []
    monkeypatch.setattr(
        backup_api,
        "generate_backup_zip_stream",
        lambda passphrase="": made.append(passphrase) or io.BytesIO(b"ZETTBAK2x"),
    )
    for body in ({}, {"passphrase": ""}, {"passphrase": "short"}):
        r = client.post("/api/system/backup", json=body, headers=auth_headers)
        assert r.status_code == 400 and "always encrypted" in r.json()["detail"], body
    assert made == []
    r = client.post("/api/system/backup", json={"passphrase": "a long enough one"}, headers=auth_headers)
    assert r.status_code == 200 and made == ["a long enough one"]
    assert r.headers["content-disposition"].endswith(".zettbak")
    # the plain download is gone
    assert client.get("/api/system/backup", headers=auth_headers).status_code in (404, 405)
