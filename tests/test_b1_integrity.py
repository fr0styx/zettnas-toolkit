"""Batch 1 of the v1.10 audit: integrity and hardening.

SEC-6 the freeze covers WebDAV and NFS, SEC-7 upload limits (and large uploads from the File
Explorer), SEC-8 scoped read endpoints and admin-only security alerts, SEC-9 streamed share-link
folder downloads, SEC-10 save errors reach the user, AI-19 no prompts to guessed ports, REL-2
damaged files found and restored, daily snapshots.
"""

import io
import json
import os
import secrets
import shutil
import sqlite3
import urllib.error
import zipfile

import pytest

from backend import fsutil
from backend.users_db import create_scoped_api_token, create_user


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _name(prefix):
    return f"{prefix}{secrets.token_hex(3)}"


@pytest.fixture
def updir(paths):
    d = os.path.join(paths["pool"], "uploads-" + secrets.token_hex(3))
    os.makedirs(d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------ SEC-7 uploads
def test_the_file_explorers_large_upload_works(client, auth_headers, updir):
    """The File Explorer sends destination_dir and no chunk count; it used to get a 422."""
    data = b"x" * 5000
    r = client.post(
        "/api/fs/upload/init",
        json={"filename": "big.bin", "destination_dir": updir, "total_size": len(data), "chunk_size": 16 * 1024 * 1024},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    uid = r.json()["upload_id"]
    assert (
        client.post(
            f"/api/fs/upload/chunk?upload_id={uid}&chunk_index=0", content=data, headers=auth_headers
        ).status_code
        == 200
    )
    r = client.post("/api/fs/upload/complete", json={"upload_id": uid}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert os.path.getsize(os.path.join(updir, "big.bin")) == len(data)


def _init(client, headers, folder, size, chunks=None):
    body = {"path": folder, "filename": "f.bin", "total_size": size}
    if chunks:
        body["total_chunks"] = chunks
    return client.post("/api/fs/upload/init", json=body, headers=headers)


def test_an_upload_cannot_send_more_than_it_announced(client, auth_headers, updir):
    uid = _init(client, auth_headers, updir, 10).json()["upload_id"]
    r = client.post(f"/api/fs/upload/chunk?upload_id={uid}&chunk_index=0", content=b"y" * 11, headers=auth_headers)
    assert r.status_code == 413
    r = client.post(f"/api/fs/upload/chunk?upload_id={uid}&chunk_index=5", content=b"y", headers=auth_headers)
    assert r.status_code == 400


def test_the_announced_size_must_be_what_arrives(client, auth_headers, updir):
    uid = _init(client, auth_headers, updir, 10).json()["upload_id"]
    client.post(f"/api/fs/upload/chunk?upload_id={uid}&chunk_index=0", content=b"y" * 4, headers=auth_headers)
    assert client.post("/api/fs/upload/complete", json={"upload_id": uid}, headers=auth_headers).status_code == 400


def test_implausible_chunk_counts_and_full_disks_are_refused(client, auth_headers, updir, monkeypatch):
    assert _init(client, auth_headers, updir, 10, chunks=50).status_code == 400
    from backend.api import fs as fs_api

    monkeypatch.setattr(fs_api.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    assert _init(client, auth_headers, updir, 10).status_code == 507


@pytest.mark.asyncio
async def test_abandoned_uploads_expire(updir):
    from backend.api import fs as fs_api

    stage = os.path.join(updir, ".zettnas_staging_old")
    os.makedirs(stage)
    fs_api._CHUNKED_UPLOADS["old"] = {"upload_id": "old", "staging_dir": stage, "created_at": 0}
    await fs_api._expire_uploads()
    assert "old" not in fs_api._CHUNKED_UPLOADS and not os.path.exists(stage)


# ------------------------------------------------------------------ SEC-9 / SEC-10 share links
def test_a_shared_folder_downloads_as_a_streamed_zip(client, auth_headers, updir):
    for i in range(3):
        with open(os.path.join(updir, f"f{i}.txt"), "w") as f:
            f.write("hello " * 100)
    token = client.post("/api/fs/share-links", json={"path": updir}, headers=auth_headers).json()["token"]
    r = client.get(f"/api/fs/shared/{token}")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert len(names) == 3 and all(n.startswith(os.path.basename(updir)) for n in names)


def test_folder_downloads_are_limited_to_two_at_once(client, auth_headers, updir, monkeypatch):
    from backend.api import fs as fs_api

    with open(os.path.join(updir, "a.txt"), "w") as f:
        f.write("a")
    token = client.post("/api/fs/share-links", json={"path": updir}, headers=auth_headers).json()["token"]
    monkeypatch.setattr(fs_api, "_SHARE_ZIP_ACTIVE", {"x": 9e18, "y": 9e18})
    r = client.get(f"/api/fs/shared/{token}")
    assert r.status_code == 429


def test_a_failed_revoke_is_reported(client, auth_headers, updir, monkeypatch):
    from backend.api import fs as fs_api

    token = client.post("/api/fs/share-links", json={"path": updir}, headers=auth_headers).json()["token"]

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fs_api, "atomic_write_json", broken)
    r = client.delete(f"/api/fs/share-links/{token}", headers=auth_headers)
    assert r.status_code == 500


# ------------------------------------------------------------------ SEC-8
@pytest.mark.parametrize(
    "path", ["/api/samba/config", "/api/copy/history", "/api/metrics", "/api/unraid", "/api/system/updates"]
)
def test_guests_cannot_read_system_details(client, path):
    guest = create_user(_name("g"), "Guest", "GoodPass123!", role_id="guest")
    raw, _ = create_scoped_api_token(guest["id"], "g", ["shares:read"])
    assert client.get(path, headers=_bearer(raw)).status_code == 403


def test_security_alerts_reach_admins_only():
    from backend.services.notifications import may_receive

    kid = create_user(_name("k"), "Kid", "GoodPass123!", role_id="kid")
    assert may_receive(kid["username"], "security") is False
    assert may_receive(kid["username"], "backup") is True
    assert may_receive("admin", "security") is True


# ------------------------------------------------------------------ SEC-6 freeze
def test_the_freeze_makes_nfs_and_webdav_read_only(monkeypatch):
    from backend.services import nfs_engine, ransomware_guard, webdav_engine

    monkeypatch.setattr(ransomware_guard, "writes_frozen", lambda: True)
    rule = nfs_engine.NfsExportRule(name="family", path="/mnt/user/family", client="192.168.1.0/24", permission="rw")
    assert nfs_engine.NfsEngine().generate_export_options(rule).startswith("ro,")

    started = []

    class _Proc:
        pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(webdav_engine.shutil, "which", lambda b: "/usr/bin/rclone")
    monkeypatch.setattr(webdav_engine.subprocess, "Popen", lambda cmd, **k: started.append(cmd) or _Proc())
    monkeypatch.setattr(webdav_engine.time, "sleep", lambda s: None)
    eng = webdav_engine.WebdavEngine()
    eng.start()
    assert "--read-only" in started[-1]
    eng._proc = None


# ------------------------------------------------------------------ AI-19
def test_chat_never_posts_prompts_to_guessed_ports(monkeypatch):
    from backend.services import ai_chat_agent
    from backend.services.chat_context import EndpointRegistry

    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(ai_chat_agent, "_get_docker_host_ips", lambda: ["10.9.9.9"])
    monkeypatch.setattr(ai_chat_agent, "_ENDPOINT_REGISTRY", EndpointRegistry())
    ai_chat_agent._ACTIVE_ENDPOINT_CACHE.clear()
    urls = []

    def urlopen(req, timeout=None):
        urls.append(req.full_url if hasattr(req, "full_url") else str(req))
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", urlopen)
    ai_chat_agent._try_local_llm_completion(
        "llama3.2:3b", "", [{"role": "user", "content": "private file text"}], fallback_model=""
    )
    assert urls and not any(p in u for u in urls for p in (":8000/", ":1234/", ":8080/"))


# ------------------------------------------------------------------ REL-2
def _good_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
        conn.execute("INSERT INTO t VALUES (1)")


def test_a_damaged_database_is_restored_from_the_newest_snapshot(tmp_path):
    from backend.services import data_health

    data = tmp_path / "data"
    snap = data / "backups" / "daily" / "20261024-030000-daily"
    snap.mkdir(parents=True)
    _good_db(str(snap / "family.db"))
    (data / "family.db").write_bytes(b"this is not a database" * 100)
    (data / "lonely.db").write_bytes(b"garbage" * 100)
    _good_db(str(data / "fine.db"))

    res = data_health.check_and_repair(str(data))
    assert res["repaired"] == {"family.db": "20261024-030000-daily"} and res["lost"] == ["lonely.db"]
    assert data_health._db_ok(str(data / "family.db"))
    kept = [p.name for p in data.iterdir() if ".corrupt-" in p.name]
    assert any(n.startswith("family.db.corrupt-") for n in kept) and any(
        n.startswith("lonely.db.corrupt-") for n in kept
    )


def test_an_unreadable_settings_file_is_set_aside(tmp_path):
    p = tmp_path / "jobs.json"
    p.write_text("{not json")
    assert fsutil.read_json(str(p), {"default": True}) == {"default": True}
    assert not p.exists() and any(".corrupt-" in q.name for q in tmp_path.iterdir())


def test_one_daily_snapshot_a_day_and_seven_kept(tmp_path):
    from backend.services import data_health

    data = tmp_path / "data"
    data.mkdir()
    (data / "settings.json").write_text(json.dumps({"a": 1}))
    assert data_health.take_daily_snapshot_if_due(str(data))
    assert data_health.take_daily_snapshot_if_due(str(data)) is None
    root = data / "backups" / "daily"
    for i in range(10):
        (root / f"2026010{i}-000000-daily").mkdir()
        (root / f"2026010{i}-000000-daily" / "manifest.json").write_text("{}")
    future = 4e9
    data_health.take_daily_snapshot_if_due(str(data), now=future)
    assert len(list(root.iterdir())) == data_health.DAILY_KEEP
