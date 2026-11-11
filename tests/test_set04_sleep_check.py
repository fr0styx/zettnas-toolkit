"""SET-04, the owner's decision S12: reading with the sleep check off is a deliberate wake.

The page could turn the check off for one "Sync" with no question, a family member could send it,
and with the setting off photo captions stopped looking at whether a drive sleeps. Now: turning
the check off (for one reading, or in the settings) needs an administrator and a confirmation,
and captions always look."""

import os

import pytest
from PIL import Image

from backend.api import media as media_api
from backend.config import POOL_PATH as POOL_DIR
from backend.services import vision_queue as vq
from backend.services.rag_engine import RagSearchEngine
from backend.users_db import create_user, delete_user, get_user_by_username


class FakeRag:
    def __init__(self, respect=True):
        self.cfg = {"watched_paths": [], "excluded_paths": [], "enabled": True, "respect_standby": respect}
        self.calls = []

    def get_config(self):
        return dict(self.cfg)

    def update_config(self, updates):
        self.calls.append(("update_config", updates))
        self.cfg.update(updates)
        return dict(self.cfg)

    def start_background_sync(self, **kw):
        self.calls.append(("start_background_sync", kw))
        return {"status": "started"}

    def index_directory(self, path, respect_standby, force_wake, max_files, recursive):
        self.calls.append(("index_directory", path, respect_standby))
        return {"indexed_files": 1}

    def get_index_stats(self):
        return {}

    def get_sync_progress(self):
        return {}


class _Media:
    def get_status(self):
        return {"acceleration": {}}


@pytest.fixture
def rag(monkeypatch):
    fake = FakeRag()
    monkeypatch.setattr(media_api, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(media_api, "get_media_engine", lambda: _Media())
    # which folders a person may open is not what these tests are about
    monkeypatch.setattr(media_api, "_validate_media_path", lambda p, principal, must_exist=False: p)
    return fake


@pytest.fixture
def folder():
    path = os.path.join(POOL_DIR, "set04_sleep")
    os.makedirs(path, exist_ok=True)
    yield path
    os.rmdir(path)


@pytest.fixture
def member(client):
    name = "set04_member"
    if not get_user_by_username(name):
        create_user(name, name, "GoodPass123!", role_id="share_user")
    res = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    yield {"Authorization": f"Bearer {res.json()['token']}"}
    delete_user(get_user_by_username(name)["id"])


def _read(calls):
    return [c for c in calls if c[0] in ("index_directory", "index_paths", "start_background_sync")]


@pytest.mark.real_confirmations
def test_a_family_member_cannot_read_with_the_check_off(client, member, rag, folder):
    r = client.post("/api/ai/index/sync", json={"path": folder, "respect_standby": False}, headers=member)
    assert r.status_code == 403 and "administrator" in r.json()["detail"]
    assert _read(rag.calls) == []
    # with the check on, their Sync works as before
    r = client.post("/api/ai/index/sync", json={"path": folder}, headers=member)
    assert r.status_code == 200 and _read(rag.calls)[-1][2] is True


@pytest.mark.real_confirmations
def test_an_administrator_is_asked_first(client, auth_headers, rag, folder):
    r = client.post("/api/ai/index/sync", json={"path": folder, "respect_standby": False}, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "ai.read_sleeping"
    assert _read(rag.calls) == []
    token = client.post(
        "/api/confirmations", json={"action": "ai.read_sleeping", "target": "indexing"}, headers=auth_headers
    ).json()["token"]
    r = client.post(
        "/api/ai/index/sync",
        json={"path": folder, "respect_standby": False},
        headers={**auth_headers, "X-Confirm-Token": token},
    )
    assert r.status_code == 200 and _read(rag.calls)[-1][2] is False


@pytest.mark.real_confirmations
def test_nothing_is_asked_where_the_check_is_already_off(client, auth_headers, member, rag, folder):
    rag.cfg["respect_standby"] = False  # an administrator turned it off, and confirmed that then
    for headers in (auth_headers, member):
        r = client.post("/api/ai/index/sync", json={"path": folder, "respect_standby": False}, headers=headers)
        assert r.status_code == 200, r.text


@pytest.mark.real_confirmations
@pytest.mark.parametrize("body", [{"respect_standby": False}, {"auto_learn_on_spinup": False}])
def test_turning_the_check_off_in_the_settings_is_asked(client, auth_headers, rag, body):
    r = client.put("/api/ai/config", json=body, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "ai.read_sleeping"
    assert rag.calls == []
    token = client.post(
        "/api/confirmations", json={"action": "ai.read_sleeping", "target": "settings"}, headers=auth_headers
    ).json()["token"]
    r = client.put("/api/ai/config", json=body, headers={**auth_headers, "X-Confirm-Token": token})
    assert r.status_code == 200 and rag.calls == [("update_config", body)]


@pytest.mark.real_confirmations
def test_turning_the_check_on_and_other_settings_are_not_asked(client, auth_headers, rag):
    for body in ({"respect_standby": True}, {"auto_learn_on_spinup": True}, {"schedule_enabled": True}):
        assert client.put("/api/ai/config", json=body, headers=auth_headers).status_code == 200, body


def test_captions_never_read_a_sleeping_drive(tmp_path, monkeypatch):
    """With the reading setting off, the caption queue used to skip the look at the drive."""
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    cfg = dict(engine.get_config())
    cfg.update({"respect_standby": False, "vision_captions": "auto"})
    monkeypatch.setattr(engine, "get_config", lambda: cfg)
    img = tmp_path / "IMG_0001.jpg"
    Image.new("RGB", (64, 48), (200, 30, 30)).save(img)
    st = os.stat(img)
    engine._index_single_file(
        str(img), img.name, ".jpg", st.st_size, st.st_mtime_ns, None, respect_standby=False, force_wake=True
    )
    described = []
    queue = vq.VisionQueue(
        engine,
        describe=lambda path, model, host: described.append(path) or ("a caption", ""),
        idle=lambda: True,
        host=lambda: "http://ollama",
        model_picker=lambda cfg, host: "gemma3:4b",
    )
    from backend.services import rag_standby

    monkeypatch.setattr(rag_standby, "resolve_path_backing_dev", lambda p: "sdb")
    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda dev: dev == "sdb")
    assert queue.process_one() == "standby"
    assert described == []
    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda dev: False)
    assert queue.process_one() == "done" and described == [str(img)]
