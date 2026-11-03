"""PERF-23: the AI index gives the space of deleted files back to the disk."""

import sqlite3

from backend.services import rag_engine_learning as lrn


def fill(path, auto_vacuum=None, rows=3000):
    conn = sqlite3.connect(path)
    if auto_vacuum is not None:
        conn.execute(f"PRAGMA auto_vacuum = {auto_vacuum}")
    conn.execute("CREATE TABLE t (a BLOB)")
    conn.executemany("INSERT INTO t VALUES (?)", [(b"x" * 4000,) for _ in range(rows)])
    conn.commit()
    conn.execute("DELETE FROM t")
    conn.commit()
    return conn


def test_nothing_to_give_back(tmp_path):
    conn = sqlite3.connect(tmp_path / "a.db")
    conn.execute("CREATE TABLE t (a)")
    assert lrn.reclaim_space(conn, str(tmp_path / "a.db")) == {
        "mode": 0,
        "free_pages": 0,
        "freed_pages": 0,
        "vacuumed": False,
    }


def test_an_incremental_index_frees_a_batch_each_night(tmp_path, monkeypatch):
    monkeypatch.setattr(lrn, "INCREMENTAL_PAGES", 1000)
    conn = fill(tmp_path / "i.db", auto_vacuum="INCREMENTAL")
    first = lrn.reclaim_space(conn, str(tmp_path / "i.db"))
    assert first["mode"] == 2 and first["freed_pages"] == 1000 and not first["vacuumed"]
    second = lrn.reclaim_space(conn, str(tmp_path / "i.db"))
    assert second["freed_pages"] > 0
    assert conn.execute("PRAGMA freelist_count").fetchone()[0] == first["free_pages"] - 1000 - second["freed_pages"]


def test_an_old_index_with_much_free_space_is_rewritten_once(tmp_path, monkeypatch):
    monkeypatch.setattr(lrn, "RECLAIM_MIN_BYTES", 1024 * 1024)
    path = tmp_path / "o.db"
    conn = fill(path)
    out = lrn.reclaim_space(conn, str(path), disk_free=lambda p: 10**12)
    assert out["vacuumed"] and out["mode"] == 2 and out["freed_pages"] == out["free_pages"]
    assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0


def test_not_without_room_for_the_copy_or_for_a_little_free_space(tmp_path, monkeypatch):
    monkeypatch.setattr(lrn, "RECLAIM_MIN_BYTES", 1024 * 1024)
    conn = fill(tmp_path / "r.db")
    out = lrn.reclaim_space(conn, str(tmp_path / "r.db"), disk_free=lambda p: 1024)
    assert not out["vacuumed"] and out["mode"] == 0 and out["free_pages"] > 0
    monkeypatch.setattr(lrn, "RECLAIM_MIN_BYTES", 10**12)
    assert not lrn.reclaim_space(conn, str(tmp_path / "r.db"))["vacuumed"]


def test_a_new_index_starts_in_incremental_mode(tmp_path, monkeypatch):
    from backend.services.rag_engine import RagSearchEngine

    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    engine._ensure_schema()
    conn = sqlite3.connect(tmp_path / "rag.db")
    assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
