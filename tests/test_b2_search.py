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
    block = src[src.index("FROM rag_photos_fts") : src.index("LIMIT 250", src.index("FROM rag_photos_fts"))]
    assert "ORDER BY raw_bm25 DESC" in block
    # chunks: keyword_top ranks the pool and the scoped fallback alike (AI-41)
    assert inspect.getsource(rag_engine_search.keyword_top).count("ORDER BY raw_bm25 DESC") == 2


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

    def flaky(text, model, host=None, timeout=1.8, target_dim=None, is_query=False, task_prompt=None, deadline=None):
        calls.append(timeout)
        return None if len(calls) == 1 else (b"", [0.1, 0.2])

    monkeypatch.setattr(rag_embeddings, "compute_neural_embedding_via_ollama", flaky)
    rag_embeddings._QUERY_VEC_CACHE.clear()
    assert rag_embeddings.compute_multimodal_query_embedding("where is my passport", model="embeddinggemma") == (
        "embeddinggemma",
        [0.1, 0.2],
    )
    # two tries within one deadline (AI-27)
    assert len(calls) == 2 and all(0 < t <= rag_embeddings.QUERY_EMBED_TIMEOUT for t in calls)
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


def test_the_benchmark_measures_an_openai_compatible_server():
    """AI-20: the model that answers on OpenVINO Model Server is benchmarked too."""
    from backend.services import model_benchmark

    def fake_stream(ep, name, prompt, max_tokens, timeout=600.0):
        return (0.5, 49, 4.5) if max_tokens > 1 else (12.0, 1, 12.0)

    res = model_benchmark.benchmark_openai("http://ovms:8000/v1", "Qwen3-4B", stream=fake_stream)
    assert res["ok"] and res["tokens_per_s"] == 12.0 and res["first_token_s"] == 0.5
    assert res["doc_first_token_s"] == 12.0 and res["runtime"] == "openai_compatible"


def test_the_benchmark_finds_the_openai_compatible_endpoint(monkeypatch):
    from backend.services import model_benchmark, rag_engine

    eng = rag_engine.get_rag_engine()
    monkeypatch.setattr(eng, "get_config", lambda: {"llm_endpoint": "http://zettnas-ovms:8000/v1/"})
    assert model_benchmark._openai_endpoint() == "http://zettnas-ovms:8000/v1"
    monkeypatch.setattr(eng, "get_config", lambda: {"llm_endpoint": "http://ollama:11434"})
    assert model_benchmark._openai_endpoint() == ""


def test_a_streamed_answer_is_timed(monkeypatch):
    from backend.services import model_benchmark

    lines = [
        b'data: {"choices":[{"delta":{"role":"assistant"}}]}\n',
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n',
        b"data: not json\n",
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n',
        b"data: [DONE]\n",
    ]

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def __iter__(self):
            return iter(lines)

    sent = []
    monkeypatch.setattr(
        model_benchmark.urllib.request, "urlopen", lambda req, timeout=None: sent.append(req) or _Resp()
    )
    first, pieces, total = model_benchmark._stream_chat("http://ovms:8000/v1", "Qwen3-4B", "hi", 96)
    assert pieces == 2 and 0 <= first <= total
    body = json.loads(sent[0].data)
    assert body["stream"] is True and body["chat_template_kwargs"] == {"enable_thinking": False}


def test_a_benchmark_run_includes_the_model_server(monkeypatch, tmp_path):
    from backend.services import model_benchmark

    monkeypatch.setattr(model_benchmark, "RESULTS_FILE", str(tmp_path / "bench.json"))
    monkeypatch.setattr(model_benchmark, "_openai_endpoint", lambda: "http://ovms:8000/v1")
    monkeypatch.setattr(model_benchmark, "chat_models", lambda host, http: [])
    monkeypatch.setattr(
        model_benchmark,
        "benchmark_openai",
        lambda ep, name: {"name": name, "ok": True, "tokens_per_s": 12.0, "size_bytes": 0},
    )

    def http(url, body=None, timeout=30.0):
        assert url == "http://ovms:8000/v1/models"
        return {"data": [{"id": "Qwen3-4B"}]}

    out = model_benchmark.run(host="http://ollama:11434", http=http)
    assert [r["name"] for r in out["results"]] == ["Qwen3-4B"] and out["recommended"]["fast"] == "Qwen3-4B"
    assert model_benchmark.status()["job"]["state"] == "done"


def test_a_failing_model_server_is_reported_not_raised():
    from backend.services import model_benchmark

    def boom(*a, **k):
        raise OSError("refused")

    res = model_benchmark.benchmark_openai("http://ovms:8000/v1", "Qwen3-4B", stream=boom)
    assert res["ok"] is False and "refused" in res["error"]
