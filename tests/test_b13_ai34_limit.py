"""B13 (AI-34): the file limit of one indexing run continues from where it stopped, files that are
gone leave the index folder by folder even when a run reaches the limit, and the run says so."""

import shutil
import sqlite3

import pytest

from backend.services.rag_engine import RagSearchEngine


@pytest.fixture
def lib(tmp_path):
    root = tmp_path / "library"
    for folder, n in (("a", 3), ("m", 4), ("z", 6)):
        (root / folder).mkdir(parents=True)
        for i in range(n):
            (root / folder / f"note_{i}.txt").write_text(f"Notes {folder} {i}: the quarterly review of item {i}.\n")
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    yield engine, root, tmp_path
    engine.close()


def _indexed(tmp_path):
    conn = sqlite3.connect(tmp_path / "rag.db")
    try:
        return sorted(r[0].split("/library/")[1] for r in conn.execute("SELECT canonical_path FROM indexed_files"))
    finally:
        conn.close()


def test_a_run_that_reaches_the_limit_goes_on_next_time(lib):
    engine, root, tmp = lib
    first = engine.index_directory(str(root), respect_standby=False, max_files=5)
    assert first["limit_reached"] and first["resume_from"].endswith("m/note_2.txt")
    assert "Reached the limit of 5 files" in engine._sync_progress["message"]
    assert len(_indexed(tmp)) == 5
    second = engine.index_directory(str(root), respect_standby=False, max_files=5)
    assert second["indexed_files"] == 5 and second["skipped_unchanged"] == 0  # no walk over the first five again
    third = engine.index_directory(str(root), respect_standby=False, max_files=5)
    assert not third["limit_reached"] and third["resume_from"] is None
    assert len(_indexed(tmp)) == 13
    assert engine._read_cursor(str(root)) == ""  # done: the next run starts at the top


def test_deleted_files_go_even_when_the_run_reaches_the_limit(lib):
    engine, root, tmp = lib
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert len(_indexed(tmp)) == 13
    (root / "a" / "note_0.txt").unlink()
    shutil.rmtree(root / "m")
    res = engine.index_directory(str(root), respect_standby=False, max_files=4)  # stops inside z
    assert res["limit_reached"]
    left = _indexed(tmp)
    assert "a/note_0.txt" not in left and not [p for p in left if p.startswith("m/")]  # a was scanned whole
    assert len([p for p in left if p.startswith("z/")]) == 6  # z wasn't finished: nothing of it removed


def test_a_folder_left_for_the_next_run_keeps_its_entries(lib):
    engine, root, tmp = lib
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    engine._write_cursor(str(root), str(root / "m" / "note_1.txt"))  # the run before stopped there
    (root / "a" / "note_1.txt").unlink()
    res = engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert not res["limit_reached"]
    assert "a/note_1.txt" in _indexed(tmp)  # a was done by the run before: not rescanned, not cleaned yet
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert "a/note_1.txt" not in _indexed(tmp)  # the full run after it cleans it


def test_an_excluded_folder_leaves_the_index(lib):
    engine, root, tmp = lib
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    engine.update_config({"excluded_paths": [str(root / "z")]})
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert not [p for p in _indexed(tmp) if p.startswith("z/")]


def test_a_file_that_fails_to_reread_keeps_its_entry(lib, monkeypatch):
    engine, root, tmp = lib
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    (root / "a" / "note_2.txt").write_text("changed, but unreadable this time\n")
    monkeypatch.setattr(engine, "_index_single_file", lambda *a, **k: None)
    res = engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert res["errors"] == 1 and "a/note_2.txt" in _indexed(tmp)


def test_an_empty_listing_does_not_empty_the_index(lib, monkeypatch):
    engine, root, tmp = lib
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    for folder in ("a", "m", "z"):
        shutil.rmtree(root / folder)  # looks like a pool that isn't mounted
    engine.index_directory(str(root), respect_standby=False, max_files=0)
    assert len(_indexed(tmp)) == 13
