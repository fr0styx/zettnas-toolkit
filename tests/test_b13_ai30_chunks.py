"""B13 (AI-30): chunks are cut at sentence ends and sized in tokens with a hard cap, so a document
extracted as one long line or written in Chinese makes normal chunks; entries made the old way are
re-made overnight only, never while someone chats, and never by waking a sleeping disk."""

import sqlite3
import time
from types import SimpleNamespace

import pytest

from backend.services import ai_activity
from backend.services import rag_engine_indexing as indexing
from backend.services import rag_engine_learning as learning
from backend.services.rag_documents import approx_tokens, generate_contextual_hierarchical_chunks, text_units
from backend.services.rag_engine import CURRENT_INDEX_VERSION, RagSearchEngine

ONE_LINE_PDF = " ".join(
    f"Clause {i}: the tenant pays the rent on the first working day of each month." for i in range(400)
)
CHINESE = "".join(f"第{i}条：租金应在每月的第一个工作日支付，逾期需支付滞纳金。" for i in range(300))


def _children(text, name="lease.pdf"):
    _t, _title, _meta, children, parents = generate_contextual_hierarchical_chunks(
        name, ".pdf", text, f"/mnt/user/docs/{name}"
    )
    return children, parents


def test_a_document_on_one_line_becomes_normal_chunks():
    children, parents = _children(ONE_LINE_PDF)
    assert len(children) > 20 and len(parents) > 3
    assert max(approx_tokens(c["raw_chunk_text"]) for c in children) <= 240
    assert all(c["line_start"] == c["line_end"] == 1 for c in children)
    assert all(c["raw_chunk_text"].rstrip().endswith((".", ":")) for c in children)  # cut at sentence ends


def test_chinese_is_sized_by_characters_not_as_english():
    children, _parents = _children(CHINESE, "租约.txt")
    assert len(children) > 30
    assert max(approx_tokens(c["raw_chunk_text"]) for c in children) <= 240


def test_a_sentence_longer_than_a_chunk_is_cut_at_spaces_and_a_run_by_length():
    units = text_units(["word " * 2000, "x" * 5000], 100)
    assert all(approx_tokens(u) <= 100 for _n, u in units)
    assert {n for n, _u in units} == {1, 2}
    assert text_units(["short line", ""], 100) == [(1, "short line"), (2, "")]


def test_the_overlap_is_small():
    children, _parents = _children(ONE_LINE_PDF)
    for a, b in zip(children, children[1:], strict=False):
        if a["parent_index"] != b["parent_index"]:
            continue
        shared = [s for s in b["raw_chunk_text"].split("\n") if s and s in a["raw_chunk_text"]]
        assert len(shared) <= 2 and sum(approx_tokens(s) for s in shared) <= 40


def test_ordinary_documents_keep_their_lines():
    text = "# Lease\n\nThe rent is due monthly.\nThe deposit is two months.\n\n## Pets\nCats are allowed.\n"
    children, parents = _children(text, "lease.md")
    assert children and children[0]["line_start"] >= 1 and parents[0]["heading_context"].startswith("Lease")
    assert "Cats are allowed." in " ".join(c["raw_chunk_text"] for c in children)


def test_the_night_window(monkeypatch):
    night = time.mktime((2026, 10, 28, 3, 0, 0, 0, 0, -1))
    day = time.mktime((2026, 10, 28, 14, 0, 0, 0, 0, -1))
    monkeypatch.setattr("backend.services.ai_activity.chat_recently_active", lambda now=None: False)
    assert ai_activity.upgrade_window_open(night) and not ai_activity.upgrade_window_open(day)
    monkeypatch.setattr("backend.services.ai_activity.chat_recently_active", lambda now=None: True)
    assert not ai_activity.upgrade_window_open(night)  # someone is chatting


@pytest.fixture
def old_index(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "lease.txt").write_text("The rent is due on the first. " * 20)
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    conn = sqlite3.connect(tmp_path / "rag.db")
    conn.execute("UPDATE indexed_files SET index_version = ?", (CURRENT_INDEX_VERSION - 1,))
    conn.commit()
    conn.close()
    yield engine, root, tmp_path
    engine.close()


def _version(tmp_path):
    conn = sqlite3.connect(tmp_path / "rag.db")
    try:
        return conn.execute("SELECT index_version FROM indexed_files").fetchone()[0]
    finally:
        conn.close()


def test_old_entries_wait_for_the_night_and_are_re_made_then(old_index, monkeypatch):
    engine, root, tmp = old_index
    monkeypatch.setattr(indexing, "upgrade_window_open", lambda now=None: False)
    res = engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert res["upgrade_waiting"] == 1 and res["skipped_unchanged"] == 1 and _version(tmp) == CURRENT_INDEX_VERSION - 1
    assert "wait for the overnight re-index" in engine._sync_progress["message"]
    monkeypatch.setattr(indexing, "upgrade_window_open", lambda now=None: True)
    res = engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert res["indexed_files"] == 1 and _version(tmp) == CURRENT_INDEX_VERSION


def test_a_changed_file_is_re_indexed_at_once_whatever_the_hour(old_index, monkeypatch):
    engine, root, tmp = old_index
    monkeypatch.setattr(indexing, "upgrade_window_open", lambda now=None: False)
    (root / "lease.txt").write_text("The rent changed. " * 20)
    assert engine.index_directory(str(root), respect_standby=False, max_files=0)["indexed_files"] == 1
    assert _version(tmp) == CURRENT_INDEX_VERSION


def test_the_night_pass_skips_sleeping_disks_and_runs_once(old_index, monkeypatch):
    engine, root, tmp = old_index
    monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: True)
    devs = {"/mnt/cache/docs": "nvme0n1", "/mnt/disk1/films": "sdb", "/mnt/cache/private": "nvme0n1"}
    monkeypatch.setattr(learning.rag_standby, "resolve_path_backing_dev", lambda p: devs.get(p))
    monkeypatch.setattr(learning.rag_standby, "is_backing_disk_in_standby", lambda d: d == "sdb")
    cfg = {"watched_paths": list(devs)}
    paths = learning.upgrade_pass_paths(engine, cfg, {"/mnt/cache/private"}, [])
    assert paths == ["/mnt/cache/docs"]
    assert learning.upgrade_pass_paths(engine, cfg, set(), []) == []  # once a night
    monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: False)
    engine._upgrade_pass_on = ""
    assert learning.upgrade_pass_paths(engine, cfg, set(), []) == []  # not by day
    assert learning.upgrade_pass_paths(SimpleNamespace(), cfg, set(), []) == []


def test_nothing_to_re_make_means_no_night_pass(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: True)
        assert learning.upgrade_pass_paths(engine, {"watched_paths": ["/mnt/cache/docs"]}, set(), []) == []
    finally:
        engine.close()
