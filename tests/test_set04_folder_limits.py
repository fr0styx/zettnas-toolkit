"""SET-04: the list of folders Kib reads is a limit, and "Forget" holds.

Anyone who may write to a share could ask the server to read any folder they can open into the
index: on the list or not, forgotten or not. The settings route stored folder lists as sent.
Ticking a forgotten folder again read it at once while it stayed on the forgotten list."""

import os

import pytest

from backend.api import media as media_api
from backend.config import POOL_PATH as POOL_DIR
from backend.services.rag_engine import RagSearchEngine
from backend.services.rag_engine_indexing import folder_inside
from backend.users_db import create_user, delete_user, get_user_by_username

WATCHED = os.path.join(POOL_DIR, "set04_watched")
OTHER = os.path.join(POOL_DIR, "set04_other")
FORGOTTEN = os.path.join(WATCHED, "diary")


class FakeRag:
    def __init__(self):
        self.cfg = {"watched_paths": [WATCHED], "excluded_paths": [FORGOTTEN], "enabled": True}
        self.calls = []

    def get_config(self):
        return dict(self.cfg)

    def update_config(self, updates):
        self.calls.append(("update_config", updates))
        self.cfg.update(updates)
        return dict(self.cfg)

    def index_directory(self, path, *a, **k):
        self.calls.append(("index_directory", path))
        return {"indexed_files": 1}

    def index_paths(self, paths, *a, **k):
        self.calls.append(("index_paths", list(paths)))
        return {"indexed_files": 1}

    def start_background_sync(self, **kw):
        self.calls.append(("start_background_sync", kw))
        return {"status": "started"}

    def remove_deferred_path(self, path):
        return 0

    def enqueue_deferred_path(self, *a, **k):
        return {}

    def discover_available_folders(self):
        return []

    def get_deferred_queue(self):
        return []

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
    monkeypatch.setattr(media_api, "is_backing_disk_in_standby", lambda p: False)
    # which folders a person may open is tested elsewhere; here every folder of the pool is theirs
    monkeypatch.setattr(media_api, "check_user_path_access", lambda path, principal: None)
    for d in (WATCHED, OTHER, FORGOTTEN):
        os.makedirs(d, exist_ok=True)
    yield fake
    for d in (FORGOTTEN, WATCHED, OTHER):
        os.rmdir(d)


@pytest.fixture
def member(client):
    name = "set04_folders_member"
    if not get_user_by_username(name):
        create_user(name, name, "GoodPass123!", role_id="share_user")
    res = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    yield {"Authorization": f"Bearer {res.json()['token']}"}
    delete_user(get_user_by_username(name)["id"])


def _read(rag):
    return [c for c in rag.calls if c[0] in ("index_directory", "index_paths", "start_background_sync")]


def test_folder_inside():
    assert folder_inside("/a/b", ["/a/b"]) == "/a/b"
    assert folder_inside("/a/b/c", ["/x", "/a/b/"]) == "/a/b"
    assert folder_inside("/a/bc", ["/a/b"]) == ""
    assert folder_inside("/a", ["/a/b", ""]) == ""


def test_a_member_reads_inside_the_chosen_folders_only(client, member, rag):
    r = client.post("/api/ai/index/sync", json={"path": OTHER}, headers=member)
    assert r.status_code == 403 and "only the folders chosen" in r.json()["detail"]
    assert _read(rag) == []
    r = client.post("/api/ai/index/sync", json={"paths": [WATCHED, OTHER]}, headers=member)
    assert r.status_code == 403 and _read(rag) == []
    inside = os.path.join(WATCHED, "holiday")
    os.makedirs(inside, exist_ok=True)
    try:
        r = client.post("/api/ai/index/sync", json={"path": inside}, headers=member)
        assert r.status_code == 200 and _read(rag)[-1][1] == os.path.realpath(inside)
    finally:
        os.rmdir(inside)


def test_an_administrator_may_read_a_folder_outside_the_list(client, auth_headers, rag):
    r = client.post("/api/ai/index/sync", json={"path": OTHER}, headers=auth_headers)
    assert r.status_code == 200 and _read(rag)[-1][1] == os.path.realpath(OTHER)


def test_a_forgotten_folder_is_refused_for_everyone(client, auth_headers, member, rag):
    for headers in (auth_headers, member):
        for path in (FORGOTTEN, os.path.join(FORGOTTEN, "2025")):
            r = client.post("/api/ai/index/sync", json={"path": path}, headers=headers)
            assert r.status_code == 400 and "forget" in r.json()["detail"], path
    assert _read(rag) == []


def test_adding_a_forgotten_folder_again_takes_it_off_the_forgotten_list(client, auth_headers, rag):
    r = client.post("/api/ai/folders", json={"action": "add", "path": FORGOTTEN}, headers=auth_headers)
    assert r.status_code == 200
    assert rag.cfg["excluded_paths"] == [] and os.path.realpath(FORGOTTEN) in rag.cfg["watched_paths"]


def test_a_folder_inside_a_forgotten_one_is_not_added(client, auth_headers, rag):
    child = os.path.join(FORGOTTEN, "2025")
    r = client.post("/api/ai/folders", json={"action": "add", "path": child}, headers=auth_headers)
    assert r.status_code == 400 and os.path.realpath(FORGOTTEN) in r.json()["detail"]
    assert rag.cfg["watched_paths"] == [WATCHED]


def test_the_settings_route_checks_folder_lists(client, auth_headers, rag):
    for bad in ("/etc", "/mnt/user/../etc", "/proc/self"):
        r = client.put("/api/ai/config", json={"watched_paths": [bad]}, headers=auth_headers)
        assert r.status_code in (400, 403), bad
        r = client.put("/api/ai/config", json={"excluded_paths": [bad]}, headers=auth_headers)
        assert r.status_code in (400, 403), bad
    assert rag.calls == []
    r = client.put("/api/ai/config", json={"watched_paths": [OTHER, "", OTHER]}, headers=auth_headers)
    assert r.status_code == 200
    assert rag.calls == [("update_config", {"watched_paths": [os.path.realpath(OTHER)]})]


def test_the_reader_itself_skips_a_forgotten_folder(tmp_path, monkeypatch):
    """The engine too: a caller that does not go through the route (the hourly pass, a tool)."""
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    diary = tmp_path / "docs" / "diary"
    diary.mkdir(parents=True)
    (diary / "today.txt").write_text("a private note about the garden")
    engine.update_config({"watched_paths": [str(tmp_path / "docs")], "excluded_paths": [str(diary)]})
    for root in (diary, diary / "sub"):
        out = engine.index_directory(str(root), respect_standby=False)
        assert out["status"] == "excluded" and out["indexed_files"] == 0
    conn = engine._get_conn()
    try:
        assert conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0] == 0
    finally:
        conn.close()
