"""B13 (AI-18): the vector index holds int8 vectors, the float vectors are stored once (in the
chunks) and score the neighbours; an index of float vectors is converted once; the scale
benchmark measures what the runner gates on."""

import importlib.util
import json
import os
import sqlite3
import struct
import sys

import pytest

from backend.services.rag_embeddings import load_sqlite_vec_extension
from backend.services.rag_engine import VEC_QUANTIZE, RagSearchEngine, vec_table


def _has_vec():
    conn = sqlite3.connect(":memory:")
    try:
        return load_sqlite_vec_extension(conn)
    finally:
        conn.close()


needs_vec = pytest.mark.skipif(not _has_vec(), reason="sqlite-vec is not available here")


def _bench():
    spec = importlib.util.spec_from_file_location("vector_bench", "scripts/vector_bench.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_index_name_and_how_vectors_go_in():
    assert vec_table(768) == "vec_chunks_768_i8" and vec_table("384") == "vec_chunks_384_i8"
    assert VEC_QUANTIZE == "vec_quantize_int8(?, 'unit')"


@needs_vec
def test_a_float_index_is_searched_until_the_int8_one_is_filled_in_the_background(tmp_path):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        engine._ensure_schema()
        model = engine.get_config().get("embedding_model")
        conn = engine._get_conn(readonly=False)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE vec_chunks_8 USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[8], "
                "file_id INTEGER, visibility_tier TEXT)"
            )
            conn.execute(
                "INSERT INTO indexed_files (file_id, canonical_path, parent_dir, file_name, file_ext, modality, size_bytes, "
                "mtime_ns, sha256_hash, indexed_at, last_verified_at) VALUES (1, '/a.md', '/', 'a.md', '.md', 'document', 1, 1, 'x', 0, 0)"
            )
            for i in range(1, 6):
                blob = struct.pack("<8f", *[((i * j) % 7 - 3) / 3.5 for j in range(8)])
                conn.execute("INSERT INTO vec_chunks_8 VALUES (?, ?, 1, 'public_share')", (i, blob))
                conn.execute(
                    "INSERT INTO document_chunks (chunk_id, file_id, chunk_index, chunk_level, source_modality, file_name, "
                    "doc_type, heading_context, structural_context, chunk_text, raw_chunk_text, doc_metadata_json, "
                    "line_start, line_end, token_count, embedding_f32, embedding_model, embedding_dim) "
                    "VALUES (?, 1, ?, 'child', 'text', 'a.md', 'generic', '', '', 't', 't', '{}', 1, 1, 1, ?, ?, 8)",
                    (i, i, blob, model),
                )
            conn.commit()
            engine._vec_table_dim = 8
            assert engine._init_vec_table(conn, 8, background=False)  # at start: nothing converted yet
            assert engine.vec_search_table() == ("vec_chunks_8", "?")  # the float index is searched
            assert conn.execute("SELECT COUNT(*) FROM vec_chunks_8_i8").fetchone()[0] == 0
        finally:
            conn.close()
        assert engine.convert_vectors(8, batch=2, pause=0) == 5  # three batches, then the end
        assert engine.vec_search_table() == ("vec_chunks_8_i8", VEC_QUANTIZE)
        conn = engine._get_conn(readonly=False)
        try:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'vec_chunks_8%'")}
            assert "vec_chunks_8" not in names
            assert conn.execute("SELECT COUNT(*) FROM vec_chunks_8_i8").fetchone()[0] == 5
            q = struct.pack("<8f", *[((3 * j) % 7 - 3) / 3.5 for j in range(8)])
            near = conn.execute(
                "SELECT chunk_id FROM vec_chunks_8_i8 WHERE embedding MATCH vec_quantize_int8(?, 'unit') AND k = 1",
                (q,),
            ).fetchone()[0]
            assert near == 3
            assert (
                engine._init_vec_table(conn, 8, background=False) and engine.vec_search_table()[0] == "vec_chunks_8_i8"
            )
        finally:
            conn.close()
    finally:
        engine.close()


@needs_vec
def test_starting_with_a_float_index_does_not_wait_for_the_conversion(tmp_path, monkeypatch):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        engine._ensure_schema()
        started = []
        monkeypatch.setattr(engine, "convert_vectors", lambda dim: started.append(dim))
        conn = engine._get_conn(readonly=False)
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE vec_chunks_8 USING vec0(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[8])"
            )
            t0 = __import__("time").time()
            assert engine._init_vec_table(conn, 8)
            assert __import__("time").time() - t0 < 1.0
        finally:
            conn.close()
        for _ in range(50):
            if started:
                break
            __import__("time").sleep(0.02)
        assert started == [8] and engine._vec_legacy == "vec_chunks_8"
    finally:
        engine.close()


@needs_vec
def test_a_chunk_vector_goes_in_as_int8(tmp_path):
    engine = RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    try:
        engine._ensure_schema()
        engine._vec_table_dim = 8
        engine._has_sqlite_vec = True
        conn = engine._get_conn(readonly=False)
        try:
            assert engine._init_vec_table(conn, 8)
            engine._vec_table_active = True
            blob = struct.pack("<8f", *[0.5, -0.5, 0.25, 0.0, 0.1, -0.9, 0.3, 0.2])
            engine.sync_vector_chunk(conn, 42, blob, 7, "public_share", dim=8)
            engine.sync_vector_chunk(conn, 43, b"short", 7, "public_share", dim=8)  # wrong size: skipped
            rows = [tuple(r) for r in conn.execute("SELECT chunk_id, length(embedding) FROM vec_chunks_8_i8")]
            assert rows == [(42, 8)]  # 8 bytes: one per value, a quarter of the float vector
        finally:
            conn.close()
    finally:
        engine.close()


@needs_vec
def test_int8_search_with_float_rescoring_finds_the_true_neighbours():
    bench = _bench()
    assert bench.recall_at_10(n=600, dim=32, clusters=12, queries=6) >= 0.95


def test_random_vectors_are_float32_in_range():
    bench = _bench()
    blob = bench.random_vectors(3, 16)
    vals = struct.unpack("<48f", blob)
    assert len(blob) == 3 * 16 * 4 and all(0.5 <= abs(v) < 1.0 for v in vals)
    assert any(v < 0 for v in vals) and any(v > 0 for v in vals)


@needs_vec
def test_the_benchmark_reports_pass_or_fail_and_keeps_numbers_local(tmp_path, monkeypatch, capsys):
    bench = _bench()
    monkeypatch.setattr(sys, "argv", ["vector_bench.py", "--chunks", "400", "--dim", "16", "--queries", "5",
                                      "--recall-chunks", "300", "--results", str(tmp_path)])  # fmt: skip
    real = bench.recall_at_10
    monkeypatch.setattr(bench, "recall_at_10", lambda n, dim: real(n, dim, 6, 4))
    assert bench.main() == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines == ["PASS recall"] or lines == ["FAIL recall"]  # a public log: no numbers
    with open(os.path.join(tmp_path, os.listdir(tmp_path)[0])) as fh:
        saved = json.load(fh)
    assert saved["values"]["p95-400"] > 0 and "recall" in saved["pass"]
