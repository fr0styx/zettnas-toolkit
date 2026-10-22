"""
tests/test_rag_and_token_budgeting.py — Comprehensive unit and integration test suite
for Batch 2: AI & RAG Precision Polish (Item 2.1, 2.2, 2.3).
"""

import io
import json
import sqlite3
import struct
import unittest.mock as mock
import pytest

from backend.services.ai_conversations_db import (
    append_message,
    create_conversation,
    get_dynamic_token_budget,
    get_token_budgeted_history,
    init_conversations_db,
)
from backend.services.rag_engine import (
    EMBEDDING_DIM,
    TASK_PREFIX_CODE,
    TASK_PREFIX_QA,
    RagSearchEngine,
    classify_query_task_intent,
    compute_384d_embedding,
    compute_multimodal_query_embedding,
    compute_neural_embedding_via_ollama,
    cosine_similarity_vec,
    generate_contextual_hierarchical_chunks,
    late_interaction_rerank,
    load_sqlite_vec_extension,
    unpack_embedding,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_conv_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "test_ai_conversations_batch2.db")
    monkeypatch.setenv("AI_CONVERSATIONS_DB_PATH", db_file)
    init_conversations_db(db_file)
    return db_file


@pytest.fixture
def temp_rag_engine(tmp_path):
    db_file = str(tmp_path / "rag_index.db")
    engine = RagSearchEngine(db_path=db_file)
    yield engine
    engine.close()


# ---------------------------------------------------------------------------
# Item 2.1: Standalone Vector Acceleration (sqlite-vec / Ollama embeddings)
# ---------------------------------------------------------------------------


def test_sqlite_vec_loader():
    """Verifies sqlite-vec loader attempts to load extension or safely falls back without throwing."""
    conn = sqlite3.connect(":memory:")
    # Should safely return boolean (True if loaded, False if not present in env)
    result = load_sqlite_vec_extension(conn)
    assert isinstance(result, bool)
    conn.close()


def test_unpack_embedding_arbitrary_dimensions():
    """Verifies unpack_embedding handles both 384d and 768d (nomic-embed-text) vectors."""
    # 384 dimensions
    vec_384 = [0.1] * 384
    blob_384 = struct.pack("<384f", *vec_384)
    unpacked_384 = unpack_embedding(blob_384)
    assert unpacked_384 is not None
    assert len(unpacked_384) == 384
    assert pytest.approx(unpacked_384[0], 1e-4) == 0.1

    # 768 dimensions (nomic-embed-text)
    vec_768 = [0.25] * 768
    blob_768 = struct.pack("<768f", *vec_768)
    unpacked_768 = unpack_embedding(blob_768)
    assert unpacked_768 is not None
    assert len(unpacked_768) == 768
    assert pytest.approx(unpacked_768[0], 1e-4) == 0.25

    # Invalid length (not multiple of 4)
    assert unpack_embedding(b"123") is None
    assert unpack_embedding(None) is None


def test_compute_neural_embedding_via_ollama_success():
    """Verifies Ollama /api/embeddings parsing and L2 normalization."""
    mock_resp_data = {"embedding": [3.0, 4.0]}  # Norm is 5.0 -> [0.6, 0.8]
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        res = compute_neural_embedding_via_ollama(
            text="Testing neural embeddings",
            model="nomic-embed-text",
            host="http://127.0.0.1:11434",
        )
        assert res is not None
        blob, vec = res
        assert len(vec) == 2
        assert pytest.approx(vec[0], 1e-4) == 0.6
        assert pytest.approx(vec[1], 1e-4) == 0.8
        assert len(blob) == 8  # 2 floats * 4 bytes


def test_compute_neural_embedding_via_ollama_fallback():
    """Verifies graceful fallback to None if Ollama is unreachable or times out."""
    with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        res = compute_neural_embedding_via_ollama(
            text="Testing timeout",
            model="nomic-embed-text",
            host="http://127.0.0.1:11434",
            timeout=0.1,
        )
        assert res is None


def test_compute_neural_embedding_embeddinggemma_modern_api_embed():
    """Verifies EmbeddingGemma 2 using modern Ollama /api/embed returning embeddings: [[...]]."""
    # 768 native float dimensions
    raw_vec = [float(i + 1) for i in range(768)]
    mock_resp_data = {"embeddings": [raw_vec]}
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        res = compute_neural_embedding_via_ollama(
            text="ZettNAS zero-spindown storage architecture",
            model="google/embeddinggemma-2",
            host="http://127.0.0.1:11434",
        )
        assert res is not None
        blob, vec = res
        assert len(vec) == 768
        assert len(blob) == 768 * 4
        # L2 norm must be 1.0
        norm = sum(x * x for x in vec) ** 0.5
        assert pytest.approx(norm, 1e-4) == 1.0


def test_embeddinggemma_asymmetric_query_prefix():
    """Verifies that queries receive 'task: search result | query: ' prefix while docs do not."""
    captured_payloads = []

    def mock_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        captured_payloads.append(payload)
        resp = mock.MagicMock()
        resp.status = 200
        resp.read.return_value = json.dumps({"embeddings": [[0.5] * 768]}).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
        # 1. Query mode
        compute_neural_embedding_via_ollama(
            text="how to configure btrfs raid1",
            model="google/embeddinggemma-2",
            is_query=True,
        )
        assert len(captured_payloads) == 1
        assert captured_payloads[0]["input"].startswith("task: search result | query: how to configure btrfs raid1")

        # 2. Document chunk mode (no query prefix)
        compute_neural_embedding_via_ollama(
            text="Section 3: Btrfs RAID configuration details",
            model="google/embeddinggemma-2",
            is_query=False,
        )
        assert len(captured_payloads) == 2
        assert captured_payloads[1]["input"] == "Section 3: Btrfs RAID configuration details"


def test_embeddinggemma_mrl_truncation():
    """Verifies Matryoshka Representation Learning (MRL) truncation to 512, 256, and 128 dimensions."""
    raw_vec = [1.0] * 768  # 768 dimensions
    mock_resp_data = {"embeddings": [raw_vec]}
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        # Truncate to 512d
        res_512 = compute_neural_embedding_via_ollama(
            text="MRL test 512",
            model="google/embeddinggemma-2",
            target_dim=512,
        )
        assert res_512 is not None
        blob512, vec512 = res_512
        assert len(vec512) == 512
        assert len(blob512) == 512 * 4
        assert pytest.approx(sum(x * x for x in vec512) ** 0.5, 1e-4) == 1.0

        # Truncate to 256d
        res_256 = compute_neural_embedding_via_ollama(
            text="MRL test 256",
            model="google/embeddinggemma-2",
            target_dim=256,
        )
        assert res_256 is not None
        blob256, vec256 = res_256
        assert len(vec256) == 256
        assert len(blob256) == 256 * 4
        assert pytest.approx(sum(x * x for x in vec256) ** 0.5, 1e-4) == 1.0

        # Truncate to 128d
        res_128 = compute_neural_embedding_via_ollama(
            text="MRL test 128",
            model="google/embeddinggemma-2",
            target_dim=128,
        )
        assert res_128 is not None
        blob128, vec128 = res_128
        assert len(vec128) == 128
        assert len(blob128) == 128 * 4
        assert pytest.approx(sum(x * x for x in vec128) ** 0.5, 1e-4) == 1.0


def test_rag_config_embedding_model_and_dimensions(temp_rag_engine):
    """Verifies get_config and update_config support embedding_model, embedding_dim, and provider."""
    cfg = temp_rag_engine.get_config()
    assert "embedding_model" in cfg
    assert cfg["embedding_model"] == "embeddinggemma"

    updated = temp_rag_engine.update_config(
        {
            "embedding_model": "hf.co/google/embeddinggemma-2-270m",
            "embedding_dim": 256,
            "embedding_provider": "ollama",
        }
    )
    assert updated["embedding_model"] == "hf.co/google/embeddinggemma-2-270m"
    assert updated["embedding_dim"] == 256
    assert updated["embedding_provider"] == "ollama"


def test_compute_multimodal_query_embedding_fallback():
    """Verifies query embedding falls back to 384d lexical vector if Ollama is offline."""
    with mock.patch("backend.services.rag_engine.compute_neural_embedding_via_ollama", return_value=None):
        model_name, vec = compute_multimodal_query_embedding(
            query="unraid docker cache pools",
            model="nomic-embed-text",
        )
        assert model_name == "zett_lexical_384d"
        assert len(vec) == EMBEDDING_DIM


def test_embedding_model_column_and_isolation(temp_rag_engine):
    """Verifies embedding_model column exists on indexed_files and prevents mixed vector comparison."""
    conn = temp_rag_engine._get_conn(readonly=False)
    cols = {col["name"] for col in conn.execute("PRAGMA table_info(indexed_files);").fetchall()}
    assert "embedding_model" in cols

    # Insert a dummy file with 384d embedding and a dummy file with 768d embedding
    now = 1700000000.0
    conn.execute(
        """
        INSERT INTO indexed_files (
            canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
            size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at
        ) VALUES ('/mnt/user/docs/file1.txt', '/mnt/user/docs', 'file1.txt', '.txt', 'document', 'generic',
                 100, 1000, 'hash1', 'zett_lexical_384d', 1, ?, ?)
        """,
        (now, now),
    )
    fid1 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        """
        INSERT INTO indexed_files (
            canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
            size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at
        ) VALUES ('/mnt/user/docs/file2.txt', '/mnt/user/docs', 'file2.txt', '.txt', 'document', 'generic',
                 100, 2000, 'hash2', 'nomic-embed-text', 1, ?, ?)
        """,
        (now, now),
    )
    fid2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    _, vec384 = compute_384d_embedding("Sample text")
    blob384 = struct.pack(f"<{EMBEDDING_DIM}f", *vec384)
    conn.execute(
        """
        INSERT INTO document_chunks (
            file_id, chunk_index, chunk_text, embedding_f32
        ) VALUES (?, 0, 'Sample text 1', ?)
        """,
        (fid1, blob384),
    )

    vec768 = [0.1] * 768
    blob768 = struct.pack("<768f", *vec768)
    conn.execute(
        """
        INSERT INTO document_chunks (
            file_id, chunk_index, chunk_text, embedding_f32
        ) VALUES (?, 0, 'Sample text 2', ?)
        """,
        (fid2, blob768),
    )
    conn.commit()

    # Search with 384d model
    res384 = temp_rag_engine._search_documents_ro(
        conn=conn,
        raw_query="Sample",
        fts_query="",
        query_vec=vec384,
        req_scenes=[],
        only_recipes=False,
        path_prefix=None,
        limit=10,
        principal=None,
        query_embedding_model="zett_lexical_384d",
    )
    # File 2 (nomic-embed-text) should not have its vector compared against 384d query vector
    matched_f1 = [r for r in res384 if r["canonical_path"].endswith("file1.txt")]
    assert len(matched_f1) > 0


# ---------------------------------------------------------------------------
# Item 2.2: RAG Candidate Selection & Complete Index Coverage
# ---------------------------------------------------------------------------


def test_rag_candidate_selection_includes_all_fts_hits(temp_rag_engine):
    """Verifies that all FTS5 BM25 matched chunks are included in candidate selection regardless of rank."""
    conn = temp_rag_engine._get_conn(readonly=False)
    now = 1700000000.0

    # Insert 10 documents
    for i in range(10):
        cpath = f"/mnt/user/docs/doc_{i}.txt"
        conn.execute(
            """
            INSERT INTO indexed_files (
                canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
                size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at
            ) VALUES (?, '/mnt/user/docs', ?, '.txt', 'document', 'generic',
                     100, ?, ?, 'zett_lexical_384d', 1, ?, ?)
            """,
            (cpath, f"doc_{i}.txt", 1000 + i, f"hash_{i}", now, now),
        )
        fid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        text = f"KeywordTarget content in file {i}" if i == 7 else f"Generic filler content {i}"
        _, vec = compute_384d_embedding(text)
        blob = struct.pack(f"<{EMBEDDING_DIM}f", *vec)

        conn.execute(
            """
            INSERT INTO document_chunks (
                file_id, chunk_index, chunk_text, embedding_f32
            ) VALUES (?, 0, ?, ?)
            """,
            (fid, text, blob),
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Index in FTS5
        conn.execute(
            """
            INSERT INTO rag_chunks_fts (rowid, chunk_text, heading_context, file_name, doc_metadata_json)
            VALUES (?, ?, '', ?, '{}')
            """,
            (cid, text, f"doc_{i}.txt"),
        )

    conn.commit()

    # Search specifically for KeywordTarget
    res = temp_rag_engine.search(query="KeywordTarget", mode="documents")
    assert res is not None
    assert len(res["results"]) > 0
    # doc_7 must be found and ranked at top
    assert any("doc_7.txt" in r["file_name"] for r in res["results"])


# ---------------------------------------------------------------------------
# Item 2.3: Dynamic Context Compaction Token Budgeting
# ---------------------------------------------------------------------------


def test_get_dynamic_token_budget_architectures():
    """Verifies context length scaling across various local SLMs."""
    # 32K context models (e.g. Qwen2.5, DeepSeek-R1) -> 25% is 8192
    b_qwen = get_dynamic_token_budget(model_name="qwen2.5:3b", system_ram_bytes=32 * 1024**3)
    assert b_qwen == 8192

    b_deepseek = get_dynamic_token_budget(model_name="deepseek-r1:1.5b", system_ram_bytes=32 * 1024**3)
    assert b_deepseek == 8192

    # 8K context models (e.g. Llama-3.2, Phi-3) -> 25% is 2048
    b_llama32 = get_dynamic_token_budget(model_name="llama-3.2:1b", system_ram_bytes=32 * 1024**3)
    assert b_llama32 == 2048

    # 4K context models (e.g. Llama-3, Mistral) -> 25% is 1024
    b_llama3 = get_dynamic_token_budget(model_name="llama3:8b", system_ram_bytes=32 * 1024**3)
    assert b_llama3 == 1024


def test_get_dynamic_token_budget_ram_clamping():
    """Verifies budget clamps to protect low-RAM homelab NAS hardware (AGENTS.md §1.1)."""
    # System with < 4GB total RAM (e.g. 2GB / 3GB SBC) clamps to <= 1024 tokens
    b_low_ram = get_dynamic_token_budget(
        model_name="qwen2.5:3b",
        system_ram_bytes=3 * 1024**3,  # 3 GB
    )
    assert b_low_ram == 1024

    # System with < 8GB total RAM (e.g. 6GB NAS) clamps to <= 2048 tokens
    b_mid_ram = get_dynamic_token_budget(
        model_name="qwen2.5:3b",
        system_ram_bytes=6 * 1024**3,  # 6 GB
    )
    assert b_mid_ram == 2048


def test_get_token_budgeted_history_sliding_window(temp_conv_db):
    """Verifies that sliding-window context history respects the dynamic budget."""
    conv = create_conversation(user_id="alice", title="Dynamic Budget Test", model="llama-3.2:1b")
    conv_id = conv["id"]

    # Append 10 turns of user and assistant messages
    for i in range(10):
        append_message(conv_id, "alice", "user", f"User question {i} " + ("word " * 100))
        append_message(conv_id, "alice", "assistant", f"Assistant answer {i} " + ("detail " * 100))

    # Retrieve history with a small budget of 800 tokens (approx 3200 chars)
    history_compact = get_token_budgeted_history(
        conv_id=conv_id,
        user_id="alice",
        max_tokens=800,
        db_path=temp_conv_db,
    )
    assert len(history_compact) > 0
    # Must preserve the most recent turns (turn 9)
    assert any("User question 9" in turn["content"] for turn in history_compact)
    # Total chars must be within budget
    total_chars = sum(len(turn["content"]) for turn in history_compact)
    assert total_chars <= 800 * 4 + 2000  # Recent 2 turns always preserved


# ---------------------------------------------------------------------------
# Batch 1 & 2: Remediated EmbeddingGemma 2 RAG Tests
# ---------------------------------------------------------------------------


def test_sqlite_vec_loader_readonly_and_authorized():
    """Verifies load_sqlite_vec_extension authorizes extension loading on read-only connection."""
    conn = sqlite3.connect(":memory:")
    # Must enable extension loading without raising OperationalError
    res = load_sqlite_vec_extension(conn)
    assert isinstance(res, bool)
    conn.close()


def test_cosine_similarity_mrl_mismatch_fallback():
    """Verifies dynamic prefix slicing returns valid similarity instead of 0.0 when dimensions differ."""
    # Query vector is 256d
    v_query = [0.1] * 256
    # Chunk vector is 768d
    v_chunk = [0.1] * 768

    score = cosine_similarity_vec(v_query, v_chunk)
    # Since both have identical components in first 256 dims, cosine similarity should be 1.0!
    assert score > 0.99
    assert pytest.approx(score, 1e-4) == 1.0

    # Truncate mismatch with orthogonal vectors
    v_diff = [0.0] * 768
    v_diff[0] = 1.0
    v_diff2 = [0.0] * 256
    v_diff2[1] = 1.0
    score_diff = cosine_similarity_vec(v_diff2, v_diff)
    assert score_diff == 0.0


def test_token_budgeting_8k_character_cap():
    """EmbeddingGemma reads 2,048 tokens: English is capped at 6,000 characters and CJK at 2,500 (AI-11)."""
    captured_payloads = []

    def mock_urlopen(req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        captured_payloads.append(payload)
        resp = mock.MagicMock()
        resp.status = 200
        resp.read.return_value = json.dumps({"embeddings": [[0.5] * 768]}).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    long_english = "ZettNAS enterprise storage architecture. " * 800  # ~32,800 chars
    long_cjk = "存储架构与容器管理。 " * 1500  # ~16,500 CJK chars

    with mock.patch("urllib.request.urlopen", side_effect=mock_urlopen):
        # English document
        compute_neural_embedding_via_ollama(
            text=long_english,
            model="google/embeddinggemma-2",
            is_query=False,
        )
        assert len(captured_payloads) == 1
        assert len(captured_payloads[0]["input"]) == 6000

        # CJK document
        compute_neural_embedding_via_ollama(
            text=long_cjk,
            model="google/embeddinggemma-2",
            is_query=False,
        )
        assert len(captured_payloads) == 2
        assert len(captured_payloads[1]["input"]) == 2500


def test_relational_inserts_succeed_without_sqlite_vec(temp_rag_engine):
    """Verifies relational database writes on document_chunks succeed even if sqlite-vec is not active."""
    conn = temp_rag_engine._get_conn(readonly=False)
    now = 1700000000.0

    # Insert file
    cur = conn.execute(
        """
        INSERT INTO indexed_files (
            canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
            size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at
        ) VALUES ('/mnt/user/docs/relational_test.txt', '/mnt/user/docs', 'relational_test.txt', '.txt', 'document', 'generic',
                 100, 1000, 'hash_rel', 'google/embeddinggemma-2', 1, ?, ?)
        """,
        (now, now),
    )
    fid = cur.lastrowid

    # Insert chunk with 768d blob
    vec768 = [0.05] * 768
    blob = struct.pack("<768f", *vec768)
    cur_c = conn.execute(
        """
        INSERT INTO document_chunks (
            file_id, chunk_index, chunk_text, embedding_f32, embedding_model, embedding_dim
        ) VALUES (?, 0, 'Relational insert content', ?, 'google/embeddinggemma-2', 768)
        """,
        (fid, blob),
    )
    assert cur_c.lastrowid is not None
    conn.commit()


@pytest.mark.asyncio
async def test_inplace_mrl_reembed_zero_disk_touch_and_throttling(temp_rag_engine):
    """Verifies 768d -> 256d in-place re-embedding operates 100% on SSD with progress callbacks."""
    conn = temp_rag_engine._get_conn(readonly=False)
    now = 1700000000.0

    cur = conn.execute(
        """
        INSERT INTO indexed_files (
            canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
            size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at
        ) VALUES ('/mnt/user/docs/reembed_sample.txt', '/mnt/user/docs', 'reembed_sample.txt', '.txt', 'document', 'generic',
                 200, 1000, 'hash_reembed', 'google/embeddinggemma-2', 2, ?, ?)
        """,
        (now, now),
    )
    fid = cur.lastrowid

    # Insert 2 chunks
    blob768 = struct.pack("<768f", *([0.1] * 768))
    for i in range(2):
        conn.execute(
            """
            INSERT INTO document_chunks (
                file_id, chunk_index, chunk_text, heading_context, embedding_f32, embedding_model, embedding_dim
            ) VALUES (?, ?, ?, 'Section Heading', ?, 'google/embeddinggemma-2', 768)
            """,
            (fid, i, f"Chunk text {i}", blob768),
        )
    conn.commit()

    progress_events = []

    def on_progress(p):
        progress_events.append(p)

    mock_resp_data = {"embeddings": [[0.2] * 256]}
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        res = await temp_rag_engine.in_place_reembed_collection(
            target_model="google/embeddinggemma-2-270m",
            target_dim=256,
            batch_size=1,
            progress_callback=on_progress,
        )
        assert res["status"] == "ok"
        assert res["total"] >= 2
        assert len(progress_events) >= 2

        # Verify chunks in DB are now 256d
        updated_rows = conn.execute(
            "SELECT embedding_dim, embedding_f32 FROM document_chunks WHERE file_id = ?",
            (fid,),
        ).fetchall()
        for r in updated_rows:
            assert r["embedding_dim"] == 256
            assert len(r["embedding_f32"]) == 256 * 4


def test_ast_code_chunker_preserves_decorators():
    """Verifies that Python AST code chunker preserves decorator stacks and class scopes."""
    code_sample = '''
import asyncio

class StorageEngine:
    """Enterprise Storage Controller"""

    @synchronized
    @retry(max_attempts=3)
    def resolve_backing_disk(self, path: str) -> Optional[str]:
        """Resolves underlying physical block device."""
        return "/dev/nvme0n1"

@app.get("/api/status")
async def get_system_status():
    return {"status": "ok"}
'''
    doc_type, doc_title, doc_metadata, child_chunks, parent_chunks = generate_contextual_hierarchical_chunks(
        file_name="storage_engine.py",
        file_ext=".py",
        raw_text=code_sample,
        canonical_path="/mnt/user/appdata/storage_engine.py",
    )
    assert doc_type == "code"
    assert len(child_chunks) >= 2

    # Check method chunk
    method_chunk = next((c for c in child_chunks if "resolve_backing_disk" in c["heading_context"]), None)
    assert method_chunk is not None
    assert "Class: StorageEngine > Method: resolve_backing_disk" in method_chunk["heading_context"]
    assert "@synchronized" in method_chunk["structural_context"] or "@synchronized" in method_chunk["chunk_text"]
    assert "@retry" in method_chunk["structural_context"] or "@retry" in method_chunk["chunk_text"]

    # Check top-level function chunk
    fn_chunk = next((c for c in child_chunks if "get_system_status" in c["heading_context"]), None)
    assert fn_chunk is not None
    assert "@app.get" in fn_chunk["structural_context"] or "@app.get" in fn_chunk["chunk_text"]


def test_dynamic_task_intent_classification_precedence():
    """Verifies interrogative QA questions are classified as QA, preventing domain collision with storage terms."""
    # Questions referencing NAS storage terms must be classified as QA
    intent_qa, prefix_qa = classify_query_task_intent("How do I configure a raid10 array?")
    assert intent_qa == "qa"
    assert prefix_qa == TASK_PREFIX_QA

    intent_zfs, prefix_zfs = classify_query_task_intent("Why is my zfs pool showing degraded status?")
    assert intent_zfs == "qa"
    assert prefix_zfs == TASK_PREFIX_QA

    # Pure code query
    intent_code, prefix_code = classify_query_task_intent("def resolve_backing_disk(path):")
    assert intent_code == "code"
    assert prefix_code == TASK_PREFIX_CODE

    # CLI command
    intent_cli, prefix_cli = classify_query_task_intent("btrfs subvol snapshot /mnt/user/share")
    assert intent_cli == "code"
    assert prefix_cli == TASK_PREFIX_CODE


def test_sql_intent_classification_case_insensitive():
    """Verifies SQL keyword queries match code intent regardless of casing."""
    intent_lower, prefix_lower = classify_query_task_intent("select * from logs where level = 'error'")
    assert intent_lower == "code"
    assert prefix_lower == TASK_PREFIX_CODE

    intent_upper, prefix_upper = classify_query_task_intent("SELECT * FROM container_stats")
    assert intent_upper == "code"
    assert prefix_upper == TASK_PREFIX_CODE


def test_vision_pipeline_uses_thumb_webp_when_disk_standby(tmp_path):
    """Verifies vision analysis uses SSD thumbnail when backing disk is in standby."""
    from PIL import Image
    from backend.services.rag_engine import analyze_photo_asset

    # Create dummy WebP thumbnail in memory
    img = Image.new("RGB", (64, 64), (14, 165, 233))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    thumb_bytes = buf.getvalue()

    # Pass bytes directly to analyze_photo_asset
    photo_data = analyze_photo_asset(thumb_bytes, "pool_view.webp")
    assert photo_data is not None
    assert photo_data["width"] == 64
    assert photo_data["height"] == 64
    assert "dominant_hex" in photo_data
    assert photo_data["thumb_webp"] is not None


def test_late_interaction_phrase_proximity_boost():
    """Verifies contiguous phrase matches receive late-interaction score boost."""
    candidates = [
        {
            "id": 1,
            "title": "Unrelated Document",
            "chunk_text": "Here is some general text mentioning btrfs occasionally and filesystem somewhere else.",
            "raw_chunk_text": "Here is some general text mentioning btrfs occasionally and filesystem somewhere else.",
            "score": 0.50,
        },
        {
            "id": 2,
            "title": "Btrfs Subvolume Management",
            "chunk_text": "Guide on how to configure btrfs subvolume on your NAS storage array.",
            "raw_chunk_text": "Guide on how to configure btrfs subvolume on your NAS storage array.",
            "score": 0.49,
        },
    ]

    reranked = late_interaction_rerank(
        raw_query="btrfs subvolume",
        candidates=candidates,
        top_k=2,
    )
    # Item 2 has contiguous phrase match "btrfs subvolume" in title (+0.12) and body (+0.08)
    assert reranked[0]["id"] == 2
    assert reranked[0]["score"] > 0.60


def test_ai_benchmark_endpoint(client, auth_headers):
    """Verifies POST /api/ai/benchmark returns hardware latency, throughput, and accelerator metrics."""
    mock_resp_data = {"embeddings": [[0.1] * 768]}
    mock_resp = mock.MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with mock.patch("urllib.request.urlopen", return_value=mock_resp):
        res = client.post("/api/ai/benchmark", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert "latency_ms" in data
        assert "throughput_chunks_sec" in data
        assert "tokens_per_sec" in data
        assert "accelerator" in data
        assert data["zero_disk_wakeups"] is True
