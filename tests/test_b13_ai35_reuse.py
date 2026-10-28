"""B13 (AI-35): a moved or renamed file keeps its index entry, a copy reuses the analysis instead of
being read and embedded again, copies are one search result, and duplicates can be listed."""

import os
import shutil
import sqlite3

import pytest

from backend.services import rag_engine_indexing
from backend.services.rag_engine import RagSearchEngine

TEXT = "Warranty for the Zephyrine dishwasher, model ZX-48, valid until 2031 with free repairs.\n"


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "library"
    (root / "manuals").mkdir(parents=True)
    (root / "manuals" / "dishwasher.txt").write_text(TEXT)
    (root / "manuals" / "other.txt").write_text("Oven manual: preheat to 180 degrees.\n")
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    yield engine, root, tmp_path
    engine.close()


def _rows(tmp_path):
    conn = sqlite3.connect(tmp_path / "rag.db")
    conn.row_factory = sqlite3.Row
    try:
        return {r["canonical_path"]: r for r in conn.execute("SELECT * FROM indexed_files")}
    finally:
        conn.close()


def _no_reading(monkeypatch):
    def read_again(*a, **k):
        raise AssertionError("the file was read and chunked again")

    monkeypatch.setattr(rag_engine_indexing, "generate_contextual_hierarchical_chunks", read_again)


def test_a_moved_file_keeps_its_entry(lib, monkeypatch):
    engine, root, tmp = lib
    before = _rows(tmp)[str(root / "manuals" / "dishwasher.txt")]
    (root / "kitchen").mkdir()
    shutil.move(root / "manuals" / "dishwasher.txt", root / "kitchen" / "zephyrine-warranty.txt")
    _no_reading(monkeypatch)
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    rows = _rows(tmp)
    moved = rows[str(root / "kitchen" / "zephyrine-warranty.txt")]
    assert moved["file_id"] == before["file_id"]
    assert str(root / "manuals" / "dishwasher.txt") not in rows
    hits = engine.search(query="zephyrine-warranty", mode="documents", match_tab="keyword")["results"]
    assert hits and hits[0]["path"] == str(root / "kitchen" / "zephyrine-warranty.txt")  # its new name is searchable


def test_a_copy_gets_the_same_analysis_without_reading_it(lib, monkeypatch):
    engine, root, tmp = lib
    (root / "backup").mkdir()
    shutil.copy2(root / "manuals" / "dishwasher.txt", root / "backup" / "dishwasher.txt")
    _no_reading(monkeypatch)
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    rows = _rows(tmp)
    a, b = rows[str(root / "manuals" / "dishwasher.txt")], rows[str(root / "backup" / "dishwasher.txt")]
    assert (
        a["file_id"] != b["file_id"] and a["chunk_count"] == b["chunk_count"] and a["sha256_hash"] == b["sha256_hash"]
    )
    conn = sqlite3.connect(tmp / "rag.db")
    try:
        counts = dict(conn.execute("SELECT file_id, COUNT(*) FROM document_chunks GROUP BY file_id").fetchall())
    finally:
        conn.close()
    assert counts[a["file_id"]] == counts[b["file_id"]] > 0


def test_copies_are_one_search_result_that_says_where_the_others_are(lib):
    engine, root, tmp = lib
    (root / "backup").mkdir()
    shutil.copy2(root / "manuals" / "dishwasher.txt", root / "backup" / "dishwasher.txt")
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    res = engine.search(query="Zephyrine", mode="documents", match_tab="keyword")
    hits = [r for r in res["results"] if "dishwasher" in r["path"]]
    assert len(hits) == 1 and len(hits[0]["also_at"]) == 1
    assert {hits[0]["path"], hits[0]["also_at"][0]} == {
        str(root / "manuals" / "dishwasher.txt"),
        str(root / "backup" / "dishwasher.txt"),
    }
    assert all("also_at" not in r for r in res["results"] if "other" in r["path"])


def test_duplicates_are_listed_with_the_space_they_take(lib):
    engine, root, tmp = lib
    (root / "backup").mkdir()
    shutil.copy2(root / "manuals" / "dishwasher.txt", root / "backup" / "dishwasher.txt")
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    dup = engine.duplicates()
    assert dup["total_groups"] == 1 and dup["wasted_bytes"] == len(TEXT)
    group = dup["groups"][0]
    assert group["kind"] == "file" and [os.path.basename(os.path.dirname(f["path"])) for f in group["files"]] == [
        "backup",
        "manuals",
    ]


def test_a_sleeping_disk_counts_as_still_there(lib, monkeypatch):
    engine, root, tmp = lib
    monkeypatch.setattr(rag_engine_indexing.rag_standby, "is_backing_disk_in_standby", lambda dev: dev == "sdz")
    assert engine._path_gone("/nowhere/at/all.txt", "sdz") is False
    assert engine._path_gone("/nowhere/at/all.txt", "") is True


def test_the_duplicates_route(client, auth_headers, monkeypatch):
    from backend.services import rag_engine

    seen = []

    class Engine:
        def duplicates(self, principal, limit):
            seen.append(limit)
            return {"groups": [], "total_groups": 0, "wasted_bytes": 0}

    monkeypatch.setattr("backend.api.media.get_rag_engine", lambda: Engine())
    res = client.get("/api/media/duplicates?limit=50", headers=auth_headers)
    assert res.status_code == 200 and res.json()["total_groups"] == 0 and seen == [50]
    assert rag_engine is not None
