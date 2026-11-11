"""SET-04: the Kib status call starts no work and tells each person only what they may see.

Every role, guests included, got all watched folder names, the drives' names, the memory size, the
whole AI settings and the household's shared favourites. Each call could also start a reading job."""

import types

import pytest

from backend import legacy_names
from backend.api import media as media_api
from backend.services import media_engine
from backend.users_db import create_user, delete_user, get_user_by_username

FULL = {
    "status": "ok",
    "enabled": True,
    "kib_status": "Idle",
    legacy_names.OLD_KIB_STATUS_KEY: "Idle",
    "is_gated": False,
    "gate_reason": None,
    "total_ram_bytes": 16 * 1024**3,
    "total_ram_gb": 16.0,
    "acceleration": {"tier_number": 3, "name": "Host CPU"},
    "hardware": {"tier_number": 3, "name": "Host CPU"},
    "llm_recommendations": {"models": [{"id": "m"}]},
    "learning_results": {"kib_status": "Idle", "succeeded_count": 2, "failed_files": []},
    "index_stats": {"total_files": 9, "db_path": "/data/rag.db"},
    "sync_progress": {"state": "running", "current_path": "/mnt/user/Private/taxes", "indexed_files": 3},
    "sync_state": "running",
    "is_scanning": True,
    "is_paused": False,
    "watched_paths": ["/mnt/user/Private", "/mnt/user/Photos"],
    "excluded_paths": ["/mnt/user/Private/diary"],
    "scope_mode": "include",
    "available_folders": [{"name": "Private", "path": "/mnt/user/Private", "backing_dev": "sdb"}],
    "indexed_count": 9,
    "last_scan_timestamp": 1.0,
    "categories": {"photos": 4},
    "standby_guard": {
        "active": True,
        "respect_standby": True,
        "sleeping_disks_count": 1,
        "sleeping_disks": ["sdb"],
        "running_disks_count": 1,
        "running_disks": ["nvme0n1"],
        "deferred_queue": [{"target_path": "/mnt/user/Private"}],
    },
}
SETTINGS = {
    "enabled": True,
    "active_model": "qwen",
    "llm_model": "qwen",
    "llm_endpoint": "http://10.0.0.5:11434",
    "rerank_endpoint": "http://10.0.0.6/rerank",
    "favorites": ["/mnt/user/Private/taxes/2025.pdf"],
    "search_history": ["divorce lawyer"],
    "watched_paths": ["/mnt/user/Private"],
}


class _Engine:
    def get_status(self, principal=None):
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in FULL.items()}


class _Rag:
    def get_config(self):
        return dict(SETTINGS)


@pytest.fixture
def status(client, monkeypatch):
    monkeypatch.setattr(media_api, "get_media_engine", lambda: _Engine())
    monkeypatch.setattr(media_api, "get_rag_engine", lambda: _Rag())
    monkeypatch.setattr(media_api, "get_ai_reindex_status", lambda: {"status": "idle"})
    made = []

    def ask(role):
        name = f"set04_status_{role}"
        if not get_user_by_username(name):
            create_user(name, name, "GoodPass123!", role_id=role)
            made.append(name)
        token = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"}).json()["token"]
        r = client.get("/api/ai/status", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        return r.json()

    yield ask
    for name in made:
        delete_user(get_user_by_username(name)["id"])


@pytest.mark.parametrize("role", ["share_user", "guest", "kid", "auditor"])
def test_other_people_get_no_folder_drive_or_setting(status, role):
    body = status(role)
    text = str(body)
    for secret in ("/mnt/user", "sdb", "nvme0n1", "10.0.0.5", "10.0.0.6", "divorce", "rag.db"):
        assert secret not in text, secret
    for key in ("watched_paths", "excluded_paths", "available_folders", "total_ram_gb", "total_ram_bytes"):
        assert key not in body, key
    for key in ("index_stats", "llm_recommendations", "scope_mode"):
        assert key not in body, key
    assert body["config"] == {"enabled": True, "active_model": "qwen", "llm_model": "qwen"}
    assert body["sync_progress"] == {"state": "running", "indexed_files": 3}
    assert body["standby_guard"] == {
        "active": True,
        "respect_standby": True,
        "sleeping_disks_count": 1,
        "running_disks_count": 1,
    }
    # what Ask Kib and AI search need is still there
    assert body["enabled"] is True and body["active_model"] == "qwen" and body["kib_status"] == "Idle"
    assert body["categories"] == {"photos": 4} and body["reindex_status"] == {"status": "idle"}


def test_the_machine_is_shown_to_those_who_see_the_system(status):
    assert status("share_user")["hardware"] == {"tier_number": 3, "name": "Host CPU"}
    for role in ("kid", "guest"):
        body = status(role)
        assert "hardware" not in body and "acceleration" not in body


def test_people_who_manage_kib_get_everything(status, client, auth_headers):
    body = client.get("/api/ai/status", headers=auth_headers).json()
    assert body["watched_paths"] == FULL["watched_paths"] and body["config"]["favorites"] == SETTINGS["favorites"]
    assert status("storage_admin")["watched_paths"] == FULL["watched_paths"]


def test_reading_the_status_starts_nothing(monkeypatch):
    """Outside the test mode the status ran the wake-up checks, which can start a reading job."""
    started = []

    class Rag:
        def __getattr__(self, name):
            if name in ("sync_watched_deferred_queue", "check_and_trigger_spinup_auto_learn", "start_background_sync"):
                return lambda *a, **k: started.append(name)
            if name == "get_config":
                return lambda: {"enabled": True}
            if name in ("discover_available_folders", "get_deferred_queue"):
                return lambda: []
            return lambda *a, **k: {}

    monkeypatch.setattr(media_engine, "get_rag_engine", lambda: Rag())
    monkeypatch.setattr(media_engine, "test_mode", lambda: False)
    monkeypatch.setattr(media_engine, "get_sleeping_disks_list", lambda: [])
    monkeypatch.setattr(media_engine, "get_running_disks_list", lambda: [])
    out = media_engine.get_media_engine().get_status(principal=types.SimpleNamespace(scopes=["*"]))
    assert out["status"] == "ok" and started == []
