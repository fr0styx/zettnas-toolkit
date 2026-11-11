"""SET-04: an empty list of folders means Kib reads nothing; a new install has no folder.

Before this, six places replaced an empty list by the whole pool: unticking the last folder
made Kib read everything, and a new install read every share nobody had chosen."""

import json
import pathlib

import pytest

from backend.services import rag_engine

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    monkeypatch.setattr(rag_engine.RagSearchEngine, "_start_spinup_watcher", lambda self: None)
    monkeypatch.setattr(rag_engine.RagSearchEngine, "_default_watched_paths", lambda self: ["/mnt/user/Photos"])
    return rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))


def _saved(tmp_path):
    return json.loads((tmp_path / "rag_config.json").read_text())


def test_a_new_install_reads_no_folder(engine, tmp_path):
    assert engine.get_config()["watched_paths"] == []
    assert _saved(tmp_path)["watched_paths"] == []  # written down once, so it is a choice from now on


def test_an_install_that_already_read_files_keeps_its_folders(engine, tmp_path):
    conn = engine._get_conn()
    try:
        conn.execute(
            "INSERT INTO indexed_files (canonical_path, parent_dir, file_name, file_ext, modality,"
            " size_bytes, mtime_ns, sha256_hash, indexed_at, last_verified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("/mnt/user/Photos/a.jpg", "/mnt/user/Photos", "a.jpg", ".jpg", "image", 1, 1, "x", 1.0, 1.0),
        )
        conn.commit()
    finally:
        conn.close()
    (tmp_path / "rag_config.json").unlink(missing_ok=True)  # an earlier install that never saved settings
    assert engine.get_config()["watched_paths"] == ["/mnt/user/Photos"]
    assert _saved(tmp_path)["watched_paths"] == ["/mnt/user/Photos"]
    # the step runs once: what is stored is the list from now on
    engine.update_config({"watched_paths": []})
    assert engine.get_config()["watched_paths"] == []


def test_new_install_defaults_do_not_count_as_an_earlier_install(engine, tmp_path):
    (tmp_path / "rag_config.json").write_text(json.dumps({"ai_role_access": {"kid": False, "guest": False}}))
    cfg = engine.get_config()
    assert cfg["watched_paths"] == [] and cfg["ai_role_access"] == {"kid": False, "guest": False}


def test_an_emptied_list_stays_empty(engine):
    engine.update_config({"watched_paths": ["/mnt/user/Photos"]})
    assert engine.update_config({"watched_paths": []})["watched_paths"] == []
    assert engine.get_config()["watched_paths"] == []


def test_reading_with_no_folder_reads_nothing(engine, monkeypatch):
    read = []
    monkeypatch.setattr(engine, "index_directory", lambda path, *a, **k: read.append(path) or {})
    out = engine.index_paths([])
    assert read == [] and out["status"] == "nothing_to_read" and out["indexed_files"] == 0


def test_the_chat_tool_reads_nothing_without_a_folder(monkeypatch):
    from backend.services import chat_nas_tools

    started = []

    class Rag:
        def get_config(self):
            return {"watched_paths": []}

        def start_background_sync(self, **kw):
            started.append(kw)
            return {"status": "started"}

    monkeypatch.setattr(
        chat_nas_tools,
        "_core",
        lambda: type("C", (), {"get_rag_engine": staticmethod(Rag), "_has_write_permission": staticmethod(lambda p, s: True)}),
    )
    monkeypatch.setattr(chat_nas_tools, "test_mode", lambda: False)
    fn = next(getattr(chat_nas_tools, n) for n in dir(chat_nas_tools) if n.endswith("trigger_ai_sync"))
    out = fn("start")
    assert out["result"]["status"] == "nothing_to_read" and started == []


def test_no_code_falls_back_to_the_whole_pool():
    """The words that did the harm: `or ["/mnt/user"]` and friends, in the server and in the page."""
    for rel in (
        "backend/services/rag_engine_indexing.py",
        "backend/api/media.py",
        "backend/services/chat_nas_tools.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert 'or ["/mnt/user"]' not in text and '[POOL_PATH or "/mnt/user"]' not in text, rel
    page = (ROOT / "frontend/src/components/management/ai.js").read_text(encoding="utf-8")
    assert "['/mnt/user']" not in page
