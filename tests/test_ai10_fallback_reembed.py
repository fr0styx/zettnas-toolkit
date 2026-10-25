"""Files stored with fallback vectors while the embedder was down get re-embedded (AI-10)."""

import struct
from unittest.mock import patch

from backend.services import rag_engine


def _fake_vectors(texts, model, target_dim=None, host=None, **k):
    return [struct.pack("<8f", *([0.5] * 8)) for _ in texts]


def _engine(tmp_path):
    with patch.object(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        eng = rag_engine.RagSearchEngine(db_path=str(tmp_path / "rag.db"))
    eng.update_config({"enabled": True, "embedding_model": "embeddinggemma"})
    return eng


def _models(eng):
    conn = eng._get_conn(readonly=True)
    try:
        files = [r[0] for r in conn.execute("SELECT embedding_model FROM indexed_files")]
        chunks = {
            r[0] for r in conn.execute("SELECT embedding_model FROM document_chunks WHERE chunk_level != 'parent'")
        }
        return files, chunks
    finally:
        conn.close()


def test_fallback_files_get_neural_vectors_once_the_model_is_back(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "plan.md").write_text("# Garden plan\nTomatoes in May, beans in June.", encoding="utf-8")
    with patch.object(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        eng = _engine(tmp_path)
        with patch.object(rag_engine, "compute_neural_embeddings_batch", return_value=None):
            eng.index_directory(str(docs), respect_standby=False)
            assert _models(eng)[0] == ["zett_lexical_384d"]
            assert eng.reembed_fallback_files()["status"] == "embedder_unavailable"
            assert _models(eng)[0] == ["zett_lexical_384d"]  # nothing half-done
        with patch.object(rag_engine, "compute_neural_embeddings_batch", side_effect=_fake_vectors):
            assert eng.reembed_fallback_files() == {"status": "ok", "files": 1}
        files, chunks = _models(eng)
        assert files == ["embeddinggemma"] and chunks == {"embeddinggemma"}


def test_nothing_runs_with_the_built_in_model_or_during_a_full_reembed(tmp_path):
    with patch.object(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        eng = _engine(tmp_path)
        eng.update_config({"embedding_model": "zett_lexical_384d"})
        assert eng.reembed_fallback_files()["status"] == "lexical_model"
        eng.update_config({"embedding_model": "embeddinggemma"})
        w = eng._get_conn(readonly=False)
        w.execute(
            "CREATE TABLE reembed_staging (chunk_id INTEGER PRIMARY KEY, embedding BLOB, model TEXT, dim INTEGER)"
        )
        w.execute("INSERT INTO reembed_staging VALUES (1, X'00', 'm', 8)")
        w.commit()
        w.close()
        assert eng.reembed_fallback_files()["status"] == "full_reembed_pending"


def test_the_fallback_check_uses_its_index_not_a_full_scan(tmp_path):
    with patch.object(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "cfg.json")):
        eng = _engine(tmp_path)
        conn = eng._get_conn(readonly=True)
        try:
            plan = " ".join(
                str(r[-1])
                for r in conn.execute(
                    "EXPLAIN QUERY PLAN SELECT file_id, file_name, file_ext, doc_title FROM indexed_files "
                    "WHERE parse_status = 'ok' AND embedding_model = 'zett_lexical_384d' ORDER BY file_id LIMIT 20"
                )
            )
        finally:
            conn.close()
    assert "idx_files_fallback_vectors" in plan
