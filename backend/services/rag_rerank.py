"""
Optional cross-encoder reranking for the AI index (AI-13).

Ollama has no rerank API, but OpenVINO Model Server (/v3/rerank), Infinity (/rerank),
Hugging Face TEI (/rerank) and Cohere-compatible servers do. When `rerank_endpoint` is
set in the AI config, the top candidates of a search are sent there with the query and
re-ordered by a blend of both scores. If the reranker is slow or down, search keeps its
original order.

The blend gives the reranker only RERANK_WEIGHT of the say, on min-max-scaled scores. On
a public retrieval benchmark (SciFact) with EmbeddingGemma, a 70% sigmoid blend made results
clearly worse while 20% scaled did not: a good embedding model is already hard to beat, so the reranker
should nudge close calls, not override the first ranking.
"""

import math
import urllib.parse
from typing import Any

import httpx

from backend.config import logger

TIMEOUT_S = 4.0
RERANK_WEIGHT = 0.2


def _norm(scores: list[float]) -> list[float]:
    """Cohere/OVMS give 0..1; TEI gives logits: squash those with a sigmoid."""
    if scores and all(0.0 <= s <= 1.0 for s in scores):
        return scores
    return [1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, s)))) for s in scores]


def _parse(body: Any, n: int) -> list[float] | None:
    out = [0.0] * n
    rows = body.get("results") if isinstance(body, dict) else body
    if not isinstance(rows, list):
        return None
    for r in rows:
        try:
            idx = int(r["index"])
            out[idx] = float(r.get("relevance_score", r.get("score")))
        except (KeyError, TypeError, ValueError, IndexError):
            return None
    return out


def endpoint_ok(url: str) -> bool:
    p = urllib.parse.urlsplit(str(url or ""))
    return (
        p.scheme in ("http", "https")
        and bool(p.hostname)
        and p.hostname not in ("169.254.169.254", "metadata.google.internal")
    )


def rerank_scores(
    query: str, docs: list[str], cfg: dict[str, Any], client: httpx.Client | None = None
) -> list[float] | None:
    url = str(cfg.get("rerank_endpoint") or "").strip()
    if not url or not docs or not endpoint_ok(url):
        return None
    payload: dict[str, Any] = {
        "query": query,
        "documents": docs,
        "texts": docs,
        "top_n": len(docs),
        "return_documents": False,
        "truncate": True,  # TEI rejects inputs past the model's length otherwise
    }
    if cfg.get("rerank_model"):
        payload["model"] = cfg["rerank_model"]
    own = client is None
    c = client or httpx.Client(timeout=TIMEOUT_S)
    try:
        r = c.post(url, json=payload)
        if r.status_code != 200:
            logger.debug(f"[Rerank] {url} answered {r.status_code}")
            return None
        scores = _parse(r.json(), len(docs))
        return _norm(scores) if scores is not None else None
    except (httpx.HTTPError, ValueError):
        logger.debug("[Rerank] reranker unavailable", exc_info=True)
        return None
    finally:
        if own:
            c.close()


def _scaled(xs: list[float]) -> list[float]:
    lo, hi = min(xs), max(xs)
    return [0.0 if hi <= lo else (x - lo) / (hi - lo) for x in xs]


def rerank_items(
    query: str, items: list[dict[str, Any]], cfg: dict[str, Any], client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """Re-orders the top `rerank_top_n` items; the rest keep their place after them."""
    if not query.strip() or not items or not cfg.get("rerank_endpoint"):
        return items
    n = max(2, min(100, int(cfg.get("rerank_top_n") or 30)))
    head, tail = items[:n], items[n:]
    docs = [
        f"{it.get('title') or it.get('name') or ''}\n{it.get('excerpt') or it.get('chunk_text') or ''}"[:2000]
        for it in head
    ]
    scores = rerank_scores(query, docs, cfg, client)
    if scores is None:
        return items
    first = [float(it.get("score") or 0.0) for it in head]
    lo, hi = min(first), max(first)
    mixed = [(1 - RERANK_WEIGHT) * a + RERANK_WEIGHT * b for a, b in zip(_scaled(first), _scaled(scores), strict=True)]
    for it, s, m in zip(head, scores, mixed, strict=True):
        it["rerank_score"] = round(s, 4)
        # back on the original scale, so these still compare fairly with photo results
        it["score"] = round(lo + m * (hi - lo), 4)
    order = sorted(range(len(head)), key=lambda i: mixed[i], reverse=True)
    head = [head[i] for i in order]
    return head + tail
