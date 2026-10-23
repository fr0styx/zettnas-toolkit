"""Re-embedding with a new model: staged, resumable, switched over in one go."""

import asyncio
import struct
from unittest import mock

import pytest

from backend.services import rag_engine as re_mod
from backend.services.rag_engine import RagSearchEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(re_mod, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = RagSearchEngine(db_path=str(tmp_path / "rag_index.db"))
    eng.update_config({"embedding_model": "old-model", "embedding_dim": 4})
    monkeypatch.setattr(eng, "_write_reindex_progress", lambda data: None)
    conn = eng._get_conn(readonly=False)
    cur = conn.execute(
        """INSERT INTO indexed_files (canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
           size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at)
           VALUES ('/mnt/user/docs/a.txt', '/mnt/user/docs', 'a.txt', '.txt', 'document', 'generic',
           10, 1, 'h', 'old-model', 3, 1, 1)"""
    )
    old = struct.pack("<4f", 1, 0, 0, 0)
    for i in range(3):
        conn.execute(
            """INSERT INTO document_chunks (file_id, chunk_index, chunk_text, heading_context, embedding_f32,
               embedding_model, embedding_dim) VALUES (?, ?, ?, '', ?, 'old-model', 4)""",
            (cur.lastrowid, i, f"text {i}", old),
        )
    conn.commit()
    conn.close()
    yield eng
    eng.close()


def chunk_models(eng):
    c = eng._get_conn(readonly=True)
    try:
        return [
            tuple(r) for r in c.execute("SELECT embedding_model, embedding_dim FROM document_chunks ORDER BY chunk_id")
        ]
    finally:
        c.close()


def new_vectors(texts, model, target_dim=None, host=None, batch_size=16):
    return [struct.pack("<4f", 0, 1, 0, 0) for _ in texts]


def test_pauses_without_touching_search_then_resumes(engine):
    calls = {"n": 0}

    def flaky(texts, *a, **k):
        calls["n"] += 1
        return new_vectors(texts, *a) if calls["n"] == 1 else None

    with mock.patch.object(re_mod, "compute_neural_embeddings_batch", side_effect=flaky):
        res = asyncio.run(
            engine.in_place_reembed_collection(
                "new-model", 4, batch_size=1, target_host="http://gpu:11434", retry_wait_s=0
            )
        )
    assert res["status"] == "paused" and res["completed"] == 1
    # nothing switched: search still runs on the old model, end to end
    assert chunk_models(engine) == [("old-model", 4)] * 3
    assert engine.get_config()["embedding_model"] == "old-model"

    seen = []

    def ok(texts, *a, **k):
        seen.extend(texts)
        return new_vectors(texts, *a)

    with mock.patch.object(re_mod, "compute_neural_embeddings_batch", side_effect=ok) as m:
        res = asyncio.run(
            engine.in_place_reembed_collection("new-model", 4, batch_size=1, target_host="http://gpu:11434")
        )
    assert res["status"] == "ok"
    assert len(seen) == 2  # the staged chunk was not embedded again
    assert m.call_args.args[3] == "http://gpu:11434"
    assert chunk_models(engine) == [("new-model", 4)] * 3
    cfg = engine.get_config()
    assert (cfg["embedding_model"], cfg["embedding_dim"], cfg["embedding_host"]) == ("new-model", 4, "http://gpu:11434")
    c = engine._get_conn(readonly=True)
    try:
        assert c.execute("SELECT COUNT(*) FROM reembed_staging").fetchone()[0] == 0
        assert c.execute("SELECT DISTINCT embedding_model FROM indexed_files").fetchall()[0][0] == "new-model"
    finally:
        c.close()


def test_same_name_as_the_old_model_still_re_embeds_everything(engine):
    """The model behind a name can change (EG1 stored as "EG2"): a new host means new vectors."""
    with mock.patch.object(re_mod, "compute_neural_embeddings_batch", side_effect=new_vectors) as m:
        res = asyncio.run(engine.in_place_reembed_collection("old-model", 4, target_host="http://gpu:11434"))
    assert res["status"] == "ok" and sum(len(c.args[0]) for c in m.call_args_list) == 3
    # run again with the same target: nothing left to do
    with mock.patch.object(re_mod, "compute_neural_embeddings_batch", side_effect=new_vectors) as m:
        asyncio.run(engine.in_place_reembed_collection("old-model", 4, target_host="http://gpu:11434"))
    assert m.call_count == 0


def test_switching_model_by_hand_drops_the_embedding_host(engine):
    engine.update_config({"embedding_host": "http://gpu:11434"})
    engine.update_config({"embedding_model": "old-model"})
    assert engine.get_config()["embedding_host"] == "http://gpu:11434"
    engine.update_config({"embedding_model": "nomic-embed-text"})
    assert engine.get_config()["embedding_host"] == ""
