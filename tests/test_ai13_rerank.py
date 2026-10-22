"""AI-13: optional reranker (OVMS / Infinity / TEI / Cohere-style) re-orders top results."""

import json

import httpx

from backend.services import rag_rerank as rr


def _items():
    return [
        {"title": "router.md", "excerpt": "Wi-Fi password is on the router", "score": 0.9},
        {"title": "invoice.pdf", "excerpt": "Hardware store invoice 12.99", "score": 0.8},
        {"title": "notes.txt", "excerpt": "shopping list", "score": 0.7},
    ]


def test_cohere_style_scores_reorder(monkeypatch):
    monkeypatch.setattr(rr, "RERANK_WEIGHT", 1.0)
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.97},
                    {"index": 0, "relevance_score": 0.10},
                    {"index": 2, "relevance_score": 0.05},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cfg = {"rerank_endpoint": "http://zettnas-ovms:8000/v3/rerank", "rerank_model": "bge-reranker-v2-m3"}
    out = rr.rerank_items("receipt from the hardware store", _items(), cfg, client)
    assert out[0]["title"] == "invoice.pdf" and out[0]["rerank_score"] == 0.97
    assert seen["truncate"] is True
    assert seen["query"].startswith("receipt") and seen["model"] == "bge-reranker-v2-m3" and len(seen["documents"]) == 3


def test_tei_logits_and_failures_keep_order(monkeypatch):
    monkeypatch.setattr(rr, "RERANK_WEIGHT", 1.0)
    tei = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json=[{"index": 0, "score": -4.0}, {"index": 1, "score": 3.0}, {"index": 2, "score": -1.0}]
            )
        )
    )
    out = rr.rerank_items("invoice", _items(), {"rerank_endpoint": "http://tei:8080/rerank"}, tei)
    assert out[0]["title"] == "invoice.pdf" and 0 < out[0]["rerank_score"] < 1
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    items = _items()
    assert rr.rerank_items("invoice", items, {"rerank_endpoint": "http://x/rerank"}, down) == items
    assert rr.rerank_items("invoice", items, {}, down) == items
    assert not rr.endpoint_ok("http://169.254.169.254/latest")


def _reranker(scores):
    return httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, json={"results": [{"index": i, "relevance_score": s} for i, s in enumerate(scores)]}
            )
        )
    )


def test_default_blend_only_settles_close_calls():
    cfg = {"rerank_endpoint": "http://tei:8080/rerank"}
    # a clear first-stage winner stays first even if the reranker prefers another result
    out = rr.rerank_items("q", _items(), cfg, _reranker([0.4, 0.9, 0.1]))
    assert [it["title"] for it in out] == ["router.md", "invoice.pdf", "notes.txt"]
    # near-ties go the reranker's way
    close = [dict(it, score=s) for it, s in zip(_items(), [0.81, 0.80, 0.5], strict=True)]
    out = rr.rerank_items("q", close, cfg, _reranker([0.1, 0.9, 0.0]))
    assert out[0]["title"] == "invoice.pdf"
    # scores stay within the original range
    assert all(0.5 <= it["score"] <= 0.81 for it in out)
