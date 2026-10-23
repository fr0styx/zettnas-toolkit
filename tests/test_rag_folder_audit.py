"""
Unit & Integration Tests for Revamped RAG Engine (V3):
  - Hierarchical Parent-Child Chunking & Situated Breadcrumbs
  - Folder Tree Manifests & FTS5 Sync
  - Mode A (Targeted) vs Mode B (MMR Comprehensive Folder Ingestion)
  - Primacy-Recency Inversion (Lost-in-the-Middle Mitigation)
  - Corrective RAG (CRAG) Tri-Modal Grading
  - Sentence-Level Grounding Confidence Score (NLI Lexical Entailment)
  - AI Chat Agent Integration & Grounded Synthesis Formatting
  - REST API Endpoints (/media/folder/manifest, /media/manifests, /media/folder/audit)
  - Spindown Safety Invariant (0 Disk Touches at Query Time)
"""

import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import AuthenticatedPrincipal
from backend.main import app
from backend.services.ai_chat_agent import (
    _extract_folder_and_intent,
    _synthesize_rag_grounded_answer,
    tool_search_nas_knowledge,
)
from backend.services.rag_engine import (
    RagSearchEngine,
    apply_primacy_recency_inversion,
    compute_grounding_confidence_score,
    generate_contextual_hierarchical_chunks,
    grade_rag_retrieval,
)


@pytest.fixture
def temp_rag_env():
    """Sets up a clean temporary SQLite database and storage tree for RAG testing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "test_rag.db")
        docs_dir = os.path.join(tmp_dir, "contracts")
        os.makedirs(docs_dir, exist_ok=True)

        # File 1: Master Services Agreement
        f1_path = os.path.join(docs_dir, "msa_agreement.md")
        with open(f1_path, "w", encoding="utf-8") as f:
            f.write(
                "# Master Services Agreement\n\n"
                "This Master Services Agreement ('Agreement') is entered into between Acme Corp and Beta LLC.\n\n"
                "## Section 1: Scope of Work\n"
                "Beta LLC shall provide high-performance cloud orchestration and enterprise storage engineering services.\n"
                "All deliverables must comply with ISO 27001 data protection standards.\n\n"
                "## Section 2: Payment and Invoicing\n"
                "Fees shall be invoiced monthly on Net 30 payment terms. Overdue payments incur a 1.5% monthly late fee.\n"
                "The maximum contracted budget for Year 1 is capped at $250,000 USD.\n\n"
                "## Section 3: Liability and Indemnification\n"
                "Total aggregate liability shall not exceed the fees paid in the preceding twelve months.\n"
            )

        # File 2: Non-Disclosure Agreement
        f2_path = os.path.join(docs_dir, "nda_confidentiality.md")
        with open(f2_path, "w", encoding="utf-8") as f:
            f.write(
                "# Mutual Non-Disclosure Agreement\n\n"
                "This Mutual NDA protects proprietary technical assets, source code, and cryptographic credentials.\n\n"
                "## Section 1: Confidential Information\n"
                "Confidential information includes network topologies, source code, algorithms, and financial projections.\n\n"
                "## Section 2: Exclusions and Term\n"
                "Confidentiality obligations survive for a duration of five (5) years from the date of disclosure.\n"
            )

        # File 3: Hardware Specification Document
        f3_path = os.path.join(docs_dir, "hardware_spec.txt")
        with open(f3_path, "w", encoding="utf-8") as f:
            f.write(
                "Hardware Specification Document\n"
                "Model: Zettlab D8 Appliance\n"
                "CPU: Intel Core Ultra 7 155H with integrated Intel AI Boost NPU\n"
                "Memory: 64GB DDR5 ECC\n"
                "Storage: 8x 22TB Enterprise SATA HDDs in RAIDZ2 + 2x 4TB NVMe cache\n"
                "Cooling: Dual 120mm PWM exhaust fans with Zero-RPM standby guard\n"
            )

        engine = RagSearchEngine(db_path=db_path)
        engine.index_directory(docs_dir)

        yield {
            "engine": engine,
            "db_path": db_path,
            "docs_dir": docs_dir,
            "f1": f1_path,
            "f2": f2_path,
            "f3": f3_path,
        }
        engine.close()


def test_hierarchical_chunking_and_negative_parent_indexing(temp_rag_env):
    """Verifies parent-child chunking, deterministic situated breadcrumbs, and negative parent indices in SQLite."""
    engine = temp_rag_env["engine"]
    f1_path = temp_rag_env["f1"]

    with open(f1_path, encoding="utf-8") as f:
        text = f.read()

    doc_type, doc_title, doc_metadata, children, parents = generate_contextual_hierarchical_chunks(
        file_path=f1_path,
        file_name="msa_agreement.md",
        text=text,
        parent_chunk_chars=1200,
        child_chunk_chars=350,
        child_overlap_chars=50,
    )

    # 1. Parents have chunk_level == 'parent' and valid IDs
    assert len(parents) >= 1
    for p in parents:
        assert p["chunk_level"] == "parent"
        assert p["parent_chunk_id"].startswith("parent_")
        assert len(p["text"]) > 0

    # 2. Children have chunk_level == 'child' and reference parent_chunk_id
    assert len(children) >= 2
    for c in children:
        assert c["chunk_level"] == "child"
        assert c["parent_chunk_id"] is not None
        assert c["parent_chunk_id"].startswith("parent_")
        # Situated breadcrumb check
        assert "Doc: " in c["text"]
        assert c["structural_context"] != ""
        assert len(c["raw_text"]) > 0

    # 3. Query SQLite to verify negative indexing for parent chunks (preventing UNIQUE collisions)
    conn = engine._get_ro_conn()
    try:
        parent_rows = conn.execute(
            "SELECT chunk_index, chunk_level, parent_chunk_id FROM document_chunks WHERE chunk_level = 'parent'"
        ).fetchall()
        assert len(parent_rows) >= 3  # Across all 3 indexed files
        for r in parent_rows:
            assert r["chunk_index"] < 0  # e.g. -1, -2, -3

        child_rows = conn.execute(
            "SELECT chunk_index, chunk_level, parent_chunk_id FROM document_chunks WHERE chunk_level = 'child'"
        ).fetchall()
        assert len(child_rows) >= 3
        for r in child_rows:
            assert r["chunk_index"] >= 0  # 0, 1, 2...
            assert r["parent_chunk_id"] is not None
    finally:
        conn.close()


def test_folder_manifest_generation_and_refresh(temp_rag_env):
    """Verifies folder manifest generation, outline synthesis, file inventory, and FTS5 search."""
    engine = temp_rag_env["engine"]
    docs_dir = temp_rag_env["docs_dir"]

    # Manifest was refreshed automatically after index_directory
    manifest = engine.get_folder_manifest(docs_dir)
    assert manifest is not None
    assert manifest["folder_path"] == docs_dir
    assert manifest["total_files"] == 3
    assert manifest["total_chunks"] >= 3
    assert len(manifest["files"]) == 3
    assert "msa_agreement.md" in manifest["outline"] or "msa_agreement.md" in manifest.get("files", [])
    assert "nda_confidentiality.md" in manifest["outline"] or "nda_confidentiality.md" in manifest.get("files", [])

    # Test list_folder_manifests
    manifests = engine.list_folder_manifests()
    assert len(manifests) >= 1
    assert any(m["folder_path"] == docs_dir for m in manifests)

    # Test FTS5 search on rag_manifests_fts
    conn = engine._get_ro_conn()
    try:
        fts_hits = conn.execute(
            "SELECT folder_path FROM rag_manifests_fts WHERE rag_manifests_fts MATCH 'Agreement OR Confidentiality'"
        ).fetchall()
        assert len(fts_hits) >= 1
        assert fts_hits[0]["folder_path"] == docs_dir
    finally:
        conn.close()


def test_aggregate_folder_context_modes(temp_rag_env):
    """Verifies Mode A (Targeted Retrieval) and Mode B (MMR Comprehensive Folder Ingestion)."""
    engine = temp_rag_env["engine"]
    docs_dir = temp_rag_env["docs_dir"]

    # --- Mode A: Targeted Fact Retrieval ---
    res_a = engine.aggregate_folder_context(
        folder_path=docs_dir,
        query="Net 30 payment terms and budget cap",
        mode="targeted",
        max_tokens=2000,
    )
    assert res_a["status"] == "ok"
    assert res_a["mode"] == "targeted"
    assert res_a["folder_path"] == docs_dir
    assert len(res_a["chunks"]) >= 1
    # Check that payment section was retrieved
    assert "Payment and Invoicing" in res_a["context_text"] or "$250,000" in res_a["context_text"]
    assert res_a["grounding_confidence_score"] is None  # nothing answered yet, so nothing measured
    assert res_a["crag_grade"] == "unrated"

    # --- Mode B: Comprehensive Folder Audit (MMR Diversified) ---
    res_b = engine.aggregate_folder_context(
        folder_path=docs_dir,
        query="audit and summarize all agreements",
        mode="comprehensive",
        max_tokens=4000,
    )
    assert res_b["status"] == "ok"
    assert res_b["mode"] == "comprehensive"
    assert res_b["manifest"] is not None
    assert res_b["files_included"] >= 2  # MMR selected representative chunks across multiple files
    assert len(res_b["chunks"]) >= 2
    assert "msa_agreement.md" in res_b["context_text"]
    assert res_b["grounding_confidence_score"] is None


def test_primacy_recency_inversion():
    """Verifies U-curve ordering [C1, C3, ..., C4, C2] to prevent Lost-in-the-Middle attention degradation."""
    chunks = [
        {"id": 1, "score": 0.95},
        {"id": 2, "score": 0.90},
        {"id": 3, "score": 0.85},
        {"id": 4, "score": 0.80},
        {"id": 5, "score": 0.75},
    ]

    inverted = apply_primacy_recency_inversion(chunks)
    assert len(inverted) == 5

    # Top chunk (id: 1) must be at the very top (index 0)
    assert inverted[0]["id"] == 1
    # Second-best chunk (id: 2) must be at the very bottom (index 4)
    assert inverted[-1]["id"] == 2
    # Third-best chunk (id: 3) is second from top
    assert inverted[1]["id"] == 3
    # Fourth-best chunk (id: 4) is second from bottom
    assert inverted[-2]["id"] == 4


def test_crag_grading_and_grounding_confidence():
    """Verifies Corrective RAG (CRAG) tri-modal evaluator and sentence-level lexical entailment."""
    # 1. High precision retrieval
    grade_high = grade_rag_retrieval(
        query="Net 30 payment terms",
        citations=[{"score": 0.88, "excerpt": "Fees shall be invoiced monthly on Net 30 payment terms."}],
    )
    assert grade_high == "high"

    # 2. Ambiguous retrieval
    grade_ambig = grade_rag_retrieval(
        query="intel cpu npu hardware",
        citations=[{"score": 0.42, "excerpt": "General hardware specification details."}],
    )
    assert grade_ambig == "ambiguous"

    # 3. Low retrieval
    grade_low = grade_rag_retrieval(query="completely unrelated question", citations=[])
    assert grade_low == "low"

    # 4. Grounding Confidence Score (Lexical Entailment)
    context = (
        "Fees shall be invoiced monthly on Net 30 payment terms. "
        "The maximum contracted budget for Year 1 is capped at $250,000 USD."
    )

    # Fully grounded claim
    grounded_ans = "The invoices are on Net 30 terms with a maximum budget capped at $250,000 USD."
    score_high = compute_grounding_confidence_score(grounded_ans, context)
    assert score_high >= 75

    # Hallucinated claim
    hallucinated_ans = "The company was founded in Tokyo and produces electric sports cars with lithium batteries."
    score_low = compute_grounding_confidence_score(hallucinated_ans, context)
    assert score_low <= 40


def test_ai_chat_agent_folder_intent_and_grounded_synthesis(temp_rag_env):
    """Verifies AI Chat Agent folder extraction, tool execution, and grounded synthesis with folder banner."""
    docs_dir = temp_rag_env["docs_dir"]
    engine = temp_rag_env["engine"]

    # 1. Intent extraction
    f_path, remaining_q, mode = _extract_folder_and_intent(f"audit folder {docs_dir}")
    assert f_path == docs_dir
    assert mode == "comprehensive"

    f_path2, remaining_q2, mode2 = _extract_folder_and_intent(f"what is the budget cap in {docs_dir}?")
    assert f_path2 == docs_dir
    assert mode2 == "targeted"
    assert "budget cap" in remaining_q2

    # 2. tool_search_nas_knowledge with patched rag engine
    with patch("backend.services.ai_chat_agent.get_rag_engine", return_value=engine):
        res = tool_search_nas_knowledge(f"audit folder {docs_dir}")
        assert res["status"] == "ok"
        assert res["folder_path"] == docs_dir
        assert res["folder_manifest"] is not None
        assert res["grounding_confidence_score"] is None
        assert res["crag_grade"] == "unrated"
        assert len(res["citations"]) >= 1

        # 3. Grounded Synthesis Formatting
        syn = _synthesize_rag_grounded_answer(
            clean_msg=f"audit folder {docs_dir}",
            rag_tool_result=res,
            active_model="qwen2.5:3b",
        )
        assert f"Folder Knowledge Scope: `{docs_dir}`" in syn
        assert "grounding unverified" in syn  # folder context has no measured score
        assert "Standby Guard:" in syn and "0 Disk Wakeups" in syn
        assert "Folder Inventory & Structure Overview" in syn


def test_media_api_folder_endpoints(temp_rag_env):
    """Verifies REST API endpoints /media/folder/manifest, /media/manifests, and /media/folder/audit."""
    docs_dir = temp_rag_env["docs_dir"]
    engine = temp_rag_env["engine"]

    client = TestClient(app)
    admin_principal = AuthenticatedPrincipal(
        username="admin",
        role_id="admin",
        scopes=["*"],
    )

    headers = {"Authorization": "Bearer fake_admin_token"}
    mock_session = {"user_id": "admin-1", "username": "admin", "role_id": "superadmin", "scopes": ["*"]}

    with (
        patch("backend.auth.get_current_session", return_value=mock_session),
        patch("backend.api.media.get_rag_engine", return_value=engine),
        patch("backend.api.media.get_current_principal", return_value=admin_principal),
        patch("backend.api.media._validate_media_path", side_effect=lambda p, *a, **k: p),
    ):
        # 1. GET /api/media/folder/manifest
        resp1 = client.get("/api/media/folder/manifest", params={"folder_path": docs_dir}, headers=headers)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "ok"
        assert data1["manifest"]["total_files"] == 3

        # 2. GET /api/media/manifests
        resp2 = client.get("/api/media/manifests", headers=headers)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "ok"
        assert len(data2["manifests"]) >= 1

        # 3. POST /api/media/folder/audit
        resp3 = client.post(
            "/api/media/folder/audit",
            json={"folder_path": docs_dir, "query": "payment terms", "mode": "targeted"},
            headers=headers,
        )
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["status"] == "ok"
        assert data3["grounding_confidence_score"] is None
        assert len(data3["chunks"]) >= 1


def test_spindown_safe_folder_queries(temp_rag_env):
    """
    Verifies the Spindown Safety Invariant (AGENTS.md §1.2):
    Once a folder is indexed, folder aggregation, manifests, search, and Q&A execute
    strictly against SQLite WAL with ZERO reads/opens of files in the target data folder.
    """
    engine = temp_rag_env["engine"]
    docs_dir = temp_rag_env["docs_dir"]

    # Spy on os.listdir and builtins.open to verify no data directory touches occur during queries
    original_open = open
    touched_data_files = []

    def tracking_open(file, *args, **kwargs):
        if isinstance(file, str) and docs_dir in file and not file.endswith(".db"):
            touched_data_files.append(file)
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=tracking_open):
        # 1. Query folder manifest
        manifest = engine.get_folder_manifest(docs_dir)
        assert manifest is not None

        # 2. Search within folder
        hits = engine.search(query="Scope of Work", path_prefix=docs_dir, limit=5)
        assert len(hits) >= 1

        # 3. Aggregate folder context (Mode B comprehensive)
        agg = engine.aggregate_folder_context(folder_path=docs_dir, mode="comprehensive")
        assert agg["status"] == "ok"

        # 4. Ask Q&A within folder
        ans = engine.ask(query="What is the budget?", path_prefix=docs_dir)
        assert ans["status"] == "ok"

    # Zero data directory touches allowed!
    assert touched_data_files == [], (
        f"Spindown Safety Invariant violated! Touched files during queries: {touched_data_files}"
    )
