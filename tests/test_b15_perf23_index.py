"""B15 (PERF-23, PERF-24): read connections get a bigger cache and the WAL is capped; the index is maintained
once a night; the newest files are found through an index; candidate vectors are scored as arrays."""

import os
import struct
import time

import pytest

from backend.services import rag_engine
from backend.services.rag_embeddings import cosine_similarity_vec, unpack_embedding, unpack_vector
from backend.services.rag_engine import RagSearchEngine


@pytest.fixture
def engine(tmp_path):
    eng = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    eng._ensure_schema()
    yield eng
    eng.close()


def test_the_newest_files_have_an_index(engine):
    conn = engine._get_conn(readonly=True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert "idx_files_ok_mtime" in names
        plan = " ".join(
            str(tuple(r))
            for r in conn.execute(
                "EXPLAIN QUERY PLAN SELECT file_id FROM indexed_files WHERE parse_status = 'ok' ORDER BY mtime_ns DESC LIMIT 10"
            )
        )
        assert "idx_files_ok_mtime" in plan and "TEMP B-TREE" not in plan
    finally:
        conn.close()


def test_write_connections_cap_the_wal(engine):
    conn = engine._get_conn(readonly=False)
    try:
        assert conn.execute("PRAGMA journal_size_limit").fetchone()[0] == rag_engine.WAL_SIZE_LIMIT_BYTES
    finally:
        conn.close()


def test_the_index_is_maintained_once_a_night(engine, monkeypatch):
    from backend.services import ai_activity

    monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: False)
    engine._maybe_maintain_index()
    assert not getattr(engine, "_maintained_on", "")  # not by day
    monkeypatch.setattr(ai_activity, "upgrade_window_open", lambda now=None: True)
    engine._maybe_maintain_index()
    assert engine._maintained_on == time.strftime("%Y-%m-%d", time.localtime())
    engine._maybe_maintain_index()  # once a night: nothing again


def test_vectors_as_arrays_score_the_same():
    vals = [0.25, -0.5, 0.125, 0.75, -0.0625, 0.5]
    blob = struct.pack(f"<{len(vals)}f", *vals)
    q = [0.5, 0.25, -0.25, 0.5, 0.125, -0.5]
    arr = unpack_vector(blob)
    assert list(arr) == unpack_embedding(blob)
    assert cosine_similarity_vec(q, arr) == pytest.approx(cosine_similarity_vec(q, unpack_embedding(blob)))
    assert cosine_similarity_vec(q[:4], arr) == pytest.approx(cosine_similarity_vec(q[:4], unpack_embedding(blob)))
    assert unpack_vector(b"") is None and unpack_vector(b"abc") is None
