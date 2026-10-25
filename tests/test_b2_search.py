"""Batch 2 of the v1.10 audit: AI search quality.

AI-1 keyword candidates ranked before the limit, AI-2 photo search beyond 2,000 photos, AI-4 a
slow embedder is retried, cached and reported, AI-6 grounding reads everything the model saw,
AI-7 the first token may take as long as the prompt needs, AI-8/15 evidence first and the
question last.
"""

import io
import json
import urllib.error

import pytest


def test_keyword_candidates_are_ranked_before_the_limit():
    """FTS5 returns rows in storage order unless asked; the 250 kept must be the best 250 (AI-1)."""
    import inspect

    from backend.services import rag_engine_search

    src = inspect.getsource(rag_engine_search)
    for table in ("rag_chunks_fts", "rag_photos_fts"):
        block = src[src.index(f"FROM {table}") : src.index("LIMIT 250", src.index(f"FROM {table}"))]
        assert "ORDER BY raw_bm25 DESC" in block, table


def test_fts5_order_by_rank_keeps_the_best_matches(tmp_path):
    """The real SQLite behaviour the fix relies on."""
    import sqlite3

    conn = sqlite3.connect(tmp_path / "f.db")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    conn.executemany(
        "INSERT INTO t(body) VALUES (?)", [("invoice filler text",)] * 400 + [("invoice invoice invoice 4711",)]
    )
    best = conn.execute(
        "SELECT rowid, -bm25(t) AS s FROM t WHERE t MATCH 'invoice' ORDER BY s DESC LIMIT 250"
    ).fetchall()
    assert best[0][0] == 401
    unordered = [r[0] for r in conn.execute("SELECT rowid FROM t WHERE t MATCH 'invoice' LIMIT 250").fetchall()]
    assert 401 not in unordered  # what the old query kept


def test_a_slow_embedder_is_retried_and_the_answer_cached(monkeypatch):
    from backend.services import rag_embeddings

    calls = []

    def flaky(text, model, host=None, timeout=1.8, target_dim=None, is_query=False, task_prompt=None):
        calls.append(timeout)
        return None if len(calls) == 1 else (b"", [0.1, 0.2])

    monkeypatch.setattr(rag_embeddings, "compute_neural_embedding_via_ollama", flaky)
    rag_embeddings._QUERY_VEC_CACHE.clear()
    assert rag_embeddings.compute_multimodal_query_embedding("where is my passport", model="embeddinggemma") == (
        "embeddinggemma",
        [0.1, 0.2],
    )
    assert calls == [rag_embeddings.QUERY_EMBED_TIMEOUT] * 2
    rag_embeddings.compute_multimodal_query_embedding("where is my passport", model="embeddinggemma")
    assert len(calls) == 2  # the second time comes from the cache


def test_no_embedder_falls_back_to_keywords(monkeypatch):
    from backend.services import rag_embeddings

    monkeypatch.setattr(rag_embeddings, "compute_neural_embedding_via_ollama", lambda *a, **k: None)
    rag_embeddings._QUERY_VEC_CACHE.clear()
    model, vec = rag_embeddings.compute_multimodal_query_embedding("tax return 2025", model="embeddinggemma")
    assert model == "zett_lexical_384d" and len(vec) == 384


def test_grounding_reads_the_whole_source():
    """A sentence supported by text beyond the 320-character excerpt is still supported (AI-6)."""
    from backend.services.rag_grounding import score_answer_grounding

    body = "Introductory remarks about the household. " * 12 + "The boiler warranty runs until March 2031."
    src = {"name": "boiler.pdf", "excerpt": body[:320], "full_parent_context": body}
    res = score_answer_grounding("The boiler warranty runs until March 2031 [1].", [src])
    assert res and res.get("supported", res.get("score", 0)) not in (0, 0.0, False)


def test_the_first_token_may_take_as_long_as_the_prompt_needs(monkeypatch):
    from backend.services import ai_chat_agent
    from backend.services.chat_context import EndpointRegistry

    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(ai_chat_agent, "_get_docker_host_ips", lambda: [])
    monkeypatch.setattr(ai_chat_agent, "_ENDPOINT_REGISTRY", EndpointRegistry())
    ai_chat_agent._ACTIVE_ENDPOINT_CACHE.clear()
    timeouts = []

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/models"):
            return _Resp(json.dumps({"data": [{"id": "m"}]}).encode())
        if url.endswith("/chat/completions"):
            timeouts.append(timeout)
            return _Resp(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())
        raise urllib.error.URLError("no")

    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", urlopen)
    long_prompt = [{"role": "user", "content": "x " * 25000}]  # about 12,500 tokens
    ai_chat_agent._try_local_llm_completion("m", "http://h:8000/v1", long_prompt, fallback_model="")
    assert timeouts and timeouts[-1] > 180


def test_the_question_comes_after_the_evidence():
    """The evidence sits in the system message (a stable prefix for caching), the question last (AI-8, AI-15)."""
    import inspect

    from backend.services import ai_chat_agent

    src = inspect.getsource(ai_chat_agent)
    assert 'user_turn_content = f"User question: {clean_msg}\\n\\nLive Context' not in src
    assert "Live Context:\\n{_build_structured_llm_context(tool_results)}" in src


def test_best_source_stays_first_for_short_lists():
    """No reordering of the few sources we send: trimming cuts from the end (AI-8)."""
    import inspect

    from backend.services import rag_engine_search

    src = inspect.getsource(rag_engine_search)
    assert "raw_citations if len(raw_citations) <= 8 else apply_primacy_recency_inversion(raw_citations)" in src
