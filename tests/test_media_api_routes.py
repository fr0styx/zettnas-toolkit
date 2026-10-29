"""The Smart Media / Ask Zetty API routes (backend/api/media.py) against a fake knowledge engine:
path checks, indexing, watched folders, model choice, settings and re-indexing."""

import asyncio
import os

import pytest

from backend.api import media as media_api
from backend.config import POOL_PATH as POOL_DIR  # the test sandbox pool (conftest)


class FakeRag:
    def __init__(self):
        self.cfg = {"watched_paths": [], "excluded_paths": [], "enabled": True, "auto_learn_on_spinup": True}
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
        self.calls.append(("index_directory", path, respect_standby, force_wake, max_files, recursive))
        return {"indexed_files": 3}

    def index_paths(self, paths, respect_standby, force_wake, max_files, recursive):
        self.calls.append(("index_paths", list(paths)))
        return {"indexed_files": 5}

    def get_index_stats(self):
        return {"files": 1}

    def get_sync_progress(self):
        return {"state": "idle"}

    def pause_sync(self):
        return {"status": "paused"}

    def resume_sync(self):
        return {"status": "resumed"}

    def stop_sync(self):
        return {"status": "stopped"}

    def flush_index(self):
        self.calls.append(("flush_index",))
        return {"status": "flushed"}

    def forget_folder(self, path):
        if path.endswith("bad"):
            raise ValueError("not learned")
        return {"status": "forgotten", "path": path}

    def discover_available_folders(self):
        return [POOL_DIR]

    def remove_deferred_path(self, path):
        self.calls.append(("remove_deferred_path", path))

    def enqueue_deferred_path(self, path, reason, priority):
        self.calls.append(("enqueue_deferred_path", path, reason))

    def get_deferred_queue(self):
        return []

    async def in_place_reembed_collection(self, target_model, target_dim, progress_callback, target_host=None):
        progress_callback({"completed": 1, "total": 2})
        if target_model == "boom":
            raise RuntimeError("embedder down")
        return {"status": "ok", "completed": 2, "total": 2}


class FakeMedia:
    def __init__(self, recs=None):
        self.recs = recs or {"models": []}
        self.scans = []

    def get_status(self):
        return {"acceleration": {"tier": "cpu"}, "total_ram_gb": 16, "llm_recommendations": self.recs}

    def trigger_scan(self, media_path):
        if media_path.endswith("locked"):
            raise PermissionError("no access")
        if media_path.endswith("broken"):
            raise RuntimeError("scanner crashed")
        self.scans.append(media_path)
        return {"status": "scanning", "path": media_path}


@pytest.fixture
def rag(monkeypatch, pool_tree):
    fake = FakeRag()
    monkeypatch.setattr(media_api, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(media_api, "is_backing_disk_in_standby", lambda p: False)
    return fake


@pytest.fixture
def media(monkeypatch):
    fake = FakeMedia()
    monkeypatch.setattr(media_api, "get_media_engine", lambda: fake)
    return fake


ADMIN = media_api.AuthenticatedPrincipal(username="admin", scopes=["*"], is_admin=True)


def _dir(name):
    path = os.path.join(POOL_DIR, "media", name)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Path checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "code"),
    [("", 400), ("bad\x00path", 400), (f"{POOL_DIR}/../etc", 403), ("/etc", 403)],
)
def test_validate_media_path_refuses_bad_paths(rag, path, code):
    with pytest.raises(media_api.HTTPException) as e:
        media_api._validate_media_path(path, ADMIN)
    assert e.value.status_code == code


def test_validate_media_path_needs_a_signed_in_user(rag):
    with pytest.raises(media_api.HTTPException) as e:
        media_api._validate_media_path(_dir("anon"), None)
    assert e.value.status_code == 401


def test_validate_media_path_missing_and_existing(rag):
    with pytest.raises(media_api.HTTPException) as e:
        media_api._validate_media_path(os.path.join(POOL_DIR, "nope"), ADMIN)
    assert e.value.status_code == 404
    assert media_api._validate_media_path(os.path.join(POOL_DIR, "nope"), ADMIN, must_exist=False).endswith("nope")
    assert media_api._validate_media_path(_dir("ok"), ADMIN) == os.path.realpath(_dir("ok"))


def test_validate_media_path_on_a_sleeping_disk_never_touches_the_folder(rag, monkeypatch):
    monkeypatch.setattr(media_api, "is_backing_disk_in_standby", lambda p: True)
    # parent exists: resolved through the parent only
    got = media_api._validate_media_path(os.path.join(POOL_DIR, "media", "asleep"), ADMIN, must_exist=False)
    assert got.endswith(os.path.join("media", "asleep"))
    # parent missing: accepted when it is inside an allowed root ...
    deep = os.path.join(POOL_DIR, "no", "such", "dir")
    assert media_api._validate_media_path(deep, ADMIN, must_exist=False) == os.path.normpath(deep)
    # ... and refused outside
    with pytest.raises(media_api.HTTPException) as e:
        media_api._validate_media_path("/nowhere/at/all", ADMIN, must_exist=False)
    assert e.value.status_code == 403
    with pytest.raises(media_api.HTTPException) as e:
        media_api._validate_media_path("/etc/sleepy", ADMIN, must_exist=False)
    assert e.value.status_code == 403


# ---------------------------------------------------------------------------
# Scanning and indexing
# ---------------------------------------------------------------------------


def test_media_scan(client, auth_headers, rag, media):
    r = client.post("/api/media/scan", json={"media_path": _dir("scan")}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "scanning"
    assert client.post("/api/media/scan", json={"media_path": _dir("locked")}, headers=auth_headers).status_code == 403
    assert client.post("/api/media/scan", json={"media_path": _dir("broken")}, headers=auth_headers).status_code == 500
    assert client.post("/api/media/scan", json={"media_path": "/etc"}, headers=auth_headers).status_code == 403


def test_media_status(client, auth_headers, rag, media):
    body = client.get("/api/ai/status", headers=auth_headers).json()
    assert body["config"]["enabled"] is True
    assert "reindex_status" in body


def test_index_one_folder_runs_in_the_request(client, auth_headers, rag, media):
    folder = _dir("docs")
    r = client.post("/api/ai/index", json={"path": folder, "max_files": 10, "recursive": False}, headers=auth_headers)
    body = r.json()
    assert r.status_code == 200 and body["indexed"] == 3
    assert body["sync_progress"] == {"state": "idle"} and body["acceleration"] == {"tier": "cpu"}
    call = next(c for c in rag.calls if c[0] == "index_directory")
    assert call[1] == os.path.realpath(folder) and call[4:] == (10, False)


def test_index_several_folders_and_duplicates(client, auth_headers, rag, media):
    a, b = _dir("a"), _dir("b")
    r = client.post("/api/ai/index/sync", json={"paths": [a, b, a, "  "]}, headers=auth_headers)
    assert r.json()["indexed"] == 5
    assert next(c for c in rag.calls if c[0] == "index_paths")[1] == [os.path.realpath(a), os.path.realpath(b)]


def test_index_defaults_to_watched_folders_then_the_pool(client, auth_headers, rag, media):
    rag.cfg["watched_paths"] = [_dir("watched")]
    client.post("/api/media/index", json={}, headers=auth_headers)
    assert rag.calls[-1][0] == "index_directory" and rag.calls[-1][1].endswith("watched")
    rag.cfg["watched_paths"] = []
    client.post("/api/media/index", json={}, headers=auth_headers)
    assert rag.calls[-1][0] == "index_directory"


def test_index_in_the_background(client, auth_headers, rag, media):
    r = client.post(
        "/api/ai/index", json={"path": _dir("bg"), "background": True, "force_wake": True}, headers=auth_headers
    )
    body = r.json()
    assert body["status"] == "started" and body["stats"] == {"files": 1}
    kw = rag.calls[-1][1]
    assert kw["force_wake"] is True and kw["paths"][0].endswith("bg")


def test_force_wake_needs_admin_scope(rag, media):
    principal = media_api.AuthenticatedPrincipal(username="u", scopes=["storage:write"], is_admin=False)
    req = media_api.RagIndexSyncRequest(path=POOL_DIR, force_wake=True)
    with pytest.raises(media_api.HTTPException) as e:
        asyncio.run(media_api.sync_rag_index(req, http_request=None, principal=principal))
    assert e.value.status_code == 403


@pytest.mark.parametrize(
    ("action", "status"),
    [("pause", "paused"), ("resume", "resumed"), ("stop", "stopped"), ("flush", "flushed"), ("status", "ok")],
)
def test_index_control(client, auth_headers, rag, media, action, status):
    body = client.post("/api/ai/index/control", json={"action": action}, headers=auth_headers).json()
    assert body["status"] == status and body["stats"] == {"files": 1}


def test_flush_and_forget(client, auth_headers, rag, media):
    assert client.post("/api/ai/index/flush", headers=auth_headers).json()["acceleration"] == {"tier": "cpu"}
    ok = client.post("/api/ai/index/forget", json={"path": _dir("old")}, headers=auth_headers)
    assert ok.json()["status"] == "forgotten"
    bad = client.post("/api/ai/index/forget", json={"path": _dir("bad")}, headers=auth_headers)
    assert bad.status_code == 400


# ---------------------------------------------------------------------------
# Watched and excluded folders
# ---------------------------------------------------------------------------


def test_folders_list(client, auth_headers, rag, monkeypatch):
    monkeypatch.setattr(media_api, "get_sleeping_disks_list", lambda: ["sdb"])
    monkeypatch.setattr(media_api, "get_running_disks_list", lambda: ["sda"])
    body = client.get("/api/ai/folders", headers=auth_headers).json()
    assert body["sleeping_disks"] == ["sdb"] and body["running_disks"] == ["sda"]
    assert body["available_folders"] == [POOL_DIR]


def test_folders_add_remove_and_set(client, auth_headers, rag):
    a, b = _dir("fa"), _dir("fb")
    r = client.post("/api/ai/folders", json={"action": "add", "path": a}, headers=auth_headers)
    assert r.json()["watched_paths"] == [os.path.realpath(a)]
    # adding twice keeps one entry; tests never start a real sync
    client.post("/api/ai/folders", json={"action": "add", "path": a}, headers=auth_headers)
    assert rag.cfg["watched_paths"] == [os.path.realpath(a)]
    assert not any(c[0] == "start_background_sync" for c in rag.calls)

    r = client.post("/api/ai/folders", json={"action": "set", "paths": [a, b, "", a]}, headers=auth_headers)
    assert r.json()["watched_paths"] == [os.path.realpath(a), os.path.realpath(b)]

    client.post("/api/ai/folders", json={"action": "remove", "path": os.path.realpath(a)}, headers=auth_headers)
    assert rag.cfg["watched_paths"] == [os.path.realpath(b)]
    # removing the last watched folder falls back to the whole pool
    client.post("/api/ai/folders", json={"action": "remove", "path": os.path.realpath(b)}, headers=auth_headers)
    assert len(rag.cfg["watched_paths"]) == 1
    assert ("remove_deferred_path", os.path.realpath(b)) in rag.calls


def test_folders_excluded_list_may_be_empty(client, auth_headers, rag):
    r = client.post("/api/ai/folders", json={"action": "set", "target": "excluded", "paths": []}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["excluded_paths"] == []
    r = client.post("/api/ai/folders", json={"action": "set", "paths": []}, headers=auth_headers)
    assert r.status_code == 400


@pytest.mark.parametrize("action", ["add", "remove"])
def test_folders_add_and_remove_need_a_path(client, auth_headers, rag, action):
    assert client.post("/api/ai/folders", json={"action": action}, headers=auth_headers).status_code == 400


def test_folder_on_a_sleeping_disk_is_queued(client, auth_headers, rag, monkeypatch):
    monkeypatch.setattr(media_api, "is_backing_disk_in_standby", lambda p: True)
    client.post("/api/ai/folders", json={"action": "add", "path": _dir("zz")}, headers=auth_headers)
    assert any(c[0] == "enqueue_deferred_path" and c[2] == "disk_standby" for c in rag.calls)


def test_folder_add_starts_learning_outside_tests(client, auth_headers, rag, monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)
    client.post("/api/ai/folders", json={"action": "add", "path": _dir("learn")}, headers=auth_headers)
    kw = next(c[1] for c in rag.calls if c[0] == "start_background_sync")
    assert kw["paths"][0].endswith("learn") and kw["force_wake"] is False


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_model_select(client, auth_headers, rag, media):
    media.recs = {
        "models": [{"id": "big:70b", "fits_hardware": False, "hardware_warning": True, "warning_message": "too big"}]
    }
    assert client.post("/api/ai/models/select", json={}, headers=auth_headers).status_code == 400
    body = client.post("/api/ai/models/select", json={"model": "BIG:70b"}, headers=auth_headers).json()
    assert body["fits_hardware"] is False and body["warning_message"] == "too big"
    assert rag.cfg["active_model"] == "BIG:70b"
    other = client.post("/api/ai/models/select", json={"model_id": "small:1b"}, headers=auth_headers).json()
    assert other["fits_hardware"] is True and other["warning_message"] is None


def test_model_select_embedding_model_keeps_the_chat_model(client, auth_headers, rag, media, monkeypatch):
    monkeypatch.setattr(media_api, "is_embedding_only_model", lambda m: "embed" in str(m))
    rag.cfg["active_model"] = "qwen3:4b"
    body = client.post("/api/ai/models/select", json={"model": "nomic-embed-text"}, headers=auth_headers).json()
    assert body["is_embedding"] is True and body["active_model"] == "qwen3:4b"
    assert rag.cfg["embedding_model"] == "nomic-embed-text"


def test_model_recommendations_mark_installed_models(client, auth_headers, rag, media, monkeypatch):
    from backend.services import media_engine, model_installer

    monkeypatch.setattr(
        media_engine,
        "build_llm_recommendations",
        lambda **kw: {"models": [{"ollama_tag": "qwen3:4b"}, {"ollama_tag": "qwen3:4b-q8"}, {"ollama_tag": "x:1b"}]},
    )
    monkeypatch.setattr(
        model_installer, "installed_models", lambda: {"reachable": True, "models": ["qwen3:4b", "qwen3:4b-q8"]}
    )
    monkeypatch.setattr(model_installer, "is_installed", lambda tag, models: tag in models)
    recs = client.get("/api/ai/models/recommendations", headers=auth_headers).json()["llm_recommendations"]
    assert [m["installed"] for m in recs["models"]] == [True, True, False]
    assert recs["runtime_reachable"] is True

    def down():
        raise OSError("ollama down")

    monkeypatch.setattr(model_installer, "installed_models", down)
    recs = client.get("/api/ai/models/recommendations", headers=auth_headers).json()["llm_recommendations"]
    assert "runtime_reachable" not in recs


def test_model_install_jobs(client, auth_headers, monkeypatch):
    from backend.services import model_installer

    def start(model, requested_by=""):
        if model == "bad":
            raise ValueError("unknown model")
        return {"job_id": "j1", "model": model, "by": requested_by}

    monkeypatch.setattr(model_installer, "start_install", start)
    monkeypatch.setattr(model_installer, "get_job", lambda j: {"id": j} if j == "j1" else None)
    monkeypatch.setattr(model_installer, "cancel_job", lambda j: j == "j1")
    assert (
        client.post("/api/ai/models/install", json={"model": "qwen3:4b"}, headers=auth_headers).json()["by"] == "admin"
    )
    assert client.post("/api/ai/models/install", json={"model": "bad"}, headers=auth_headers).status_code == 400
    assert client.get("/api/ai/models/install/j1", headers=auth_headers).json() == {"id": "j1"}
    assert client.get("/api/ai/models/install/j2", headers=auth_headers).status_code == 404
    assert client.post("/api/ai/models/install/j1/cancel", headers=auth_headers).json() == {"cancelled": True}


def test_model_remove_routes(client, auth_headers, monkeypatch):
    from backend.services import media_engine

    def remove(tag):
        if tag == "locked":
            raise ValueError("in use")
        return {"status": "removed", "model": tag}

    monkeypatch.setattr(media_engine, "remove_llm_model", remove)
    assert client.post("/api/ai/models/remove", json={"model": "a:1b"}, headers=auth_headers).json()["model"] == "a:1b"
    assert client.post("/api/ai/models/remove", json={}, headers=auth_headers).status_code == 400
    assert client.post("/api/ai/models/remove", json={"model_id": "locked"}, headers=auth_headers).status_code == 400
    assert client.delete("/api/ai/models/remove?model=b:1b", headers=auth_headers).json()["model"] == "b:1b"
    assert client.delete("/api/ai/models/remove", headers=auth_headers).status_code == 400
    assert client.delete("/api/ai/models/remove?model_id=locked", headers=auth_headers).status_code == 400
    assert client.delete("/api/ai/models/c:2b", headers=auth_headers).json()["model"] == "c:2b"
    assert client.delete("/api/ai/models/locked", headers=auth_headers).status_code == 400


def test_benchmark_tier(client, auth_headers, rag, monkeypatch):
    from backend.services import model_benchmark

    monkeypatch.setattr(model_benchmark, "load_results", lambda: {"recommended": {"fast": "qwen3:1.7b"}})
    body = client.post("/api/ai/models/benchmark/apply", json={"tier": "fast"}, headers=auth_headers).json()
    assert body == {"active_model": "qwen3:1.7b", "tier": "fast"} and rag.cfg["active_model"] == "qwen3:1.7b"
    assert (
        client.post("/api/ai/models/benchmark/apply", json={"tier": "balanced"}, headers=auth_headers).status_code
        == 409
    )


def test_hugging_face_pull_errors(client, auth_headers, monkeypatch):
    def pull(repo_id, activate):
        raise ValueError("not a model repo")

    monkeypatch.setattr(media_api, "pull_huggingface_model", pull)
    r = client.post("/api/ai/models/huggingface/pull", json={"repo_id": "x/y"}, headers=auth_headers)
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Settings and re-indexing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"llm_endpoint": "ftp://host/"},
        {"llm_endpoint": "http://169.254.169.254/"},
        {"llm_endpoint": "http://metadata.google.internal/"},
        {"rerank_endpoint": "file:///etc/passwd"},
        {"embedding_host": "gopher://x"},
    ],
)
def test_config_refuses_unsafe_endpoints(client, auth_headers, rag, body):
    assert client.put("/api/ai/config", json=body, headers=auth_headers).status_code == 400


def test_config_saves_only_given_fields(client, auth_headers, rag):
    body = client.put(
        "/api/ai/config", json={"llm_endpoint": "http://ollama:11434", "idle_unload_minutes": 5}, headers=auth_headers
    ).json()
    assert body["llm_endpoint"] == "http://ollama:11434" and body["idle_unload_minutes"] == 5
    assert rag.calls[-1] == ("update_config", {"llm_endpoint": "http://ollama:11434", "idle_unload_minutes": 5})
    assert client.get("/api/ai/config", headers=auth_headers).json()["idle_unload_minutes"] == 5


def _reindex(req=None):
    async def go():
        first = await media_api.trigger_ai_reindex(req)
        again = await media_api.trigger_ai_reindex(req)
        await media_api._REINDEX_TASK
        return first, again

    return asyncio.run(go())


def test_reindex_runs_once_and_reports_progress(rag):
    rag.cfg["embedding_model"] = "embeddinggemma"
    first, again = _reindex()
    assert first == {"status": "started", "model": "embeddinggemma", "dimension": 768, "embedding_host": ""}
    assert again["status"] == "in_progress"
    status = media_api.get_ai_reindex_status()
    assert status["status"] == "complete" and status["completed"] == 2


def test_reindex_failure_is_reported(rag):
    _reindex(media_api.RagConfigUpdateRequest(embedding_model="boom", embedding_dim=256))
    status = media_api.get_ai_reindex_status()
    assert status["status"] == "error" and "embedder down" in status["error"]


def test_reindex_refuses_a_bad_embedding_host(rag):
    with pytest.raises(media_api.HTTPException) as e:
        asyncio.run(media_api.trigger_ai_reindex(media_api.RagConfigUpdateRequest(embedding_host="ftp://x")))
    assert e.value.status_code == 400
