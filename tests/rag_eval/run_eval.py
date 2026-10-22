"""Retrieval evaluation over tests/rag_eval (AI-11).

40 home-NAS files in English, German, Chinese, French and Spanish (Markdown, text, CSV,
YAML, JSON, HTML, Python and shell) and 200 hand-written queries, 5 per file, asked the
way a person would ask. Files go through the real indexer and queries through the real
search; nothing here is tuned to the engine.

    python -m tests.rag_eval.run_eval                      # built-in lexical vectors (what CI runs)
    python -m tests.rag_eval.run_eval --model embeddinggemma   # a neural model served by Ollama
"""

import argparse
import json
import os
import tempfile
from typing import Optional
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
FIXED_MTIME_NS = 1_700_000_000_000_000_000


def load_queries() -> list[dict]:
    with open(os.path.join(HERE, "queries.json"), encoding="utf-8") as f:
        return json.load(f)


def _metrics(ranked: list[str], relevant: list[str]) -> dict[str, float]:
    rr = 0.0
    for i, p in enumerate(ranked[:10], start=1):
        if p in relevant:
            rr = 1.0 / i
            break
    return {
        "recall@1": float(any(p in relevant for p in ranked[:1])),
        "recall@5": float(any(p in relevant for p in ranked[:5])),
        "mrr@10": rr,
    }


def evaluate(model: str = "zett_lexical_384d", dim: int | None = None) -> dict:
    from backend.services.rag_engine import RagSearchEngine

    tmp = tempfile.mkdtemp(prefix="zettnas-rag-eval-")
    engine = RagSearchEngine(db_path=os.path.join(tmp, "eval.db"))
    cfg = dict(engine.get_config())
    cfg.update({"embedding_model": model, "respect_standby": False})
    if dim:
        cfg["embedding_dim"] = dim
    rel = lambda p: os.path.relpath(p, CORPUS).replace(os.sep, "/")  # noqa: E731
    per_query = []
    try:
        with (
            patch.object(engine, "get_config", return_value=cfg),
            patch("backend.services.rag_engine.is_backing_disk_in_standby", return_value=False),
        ):
            # Fixed order and timestamps, so results don't depend on the checkout
            for dirpath, dirs, files in os.walk(CORPUS):
                dirs.sort()
                for name in sorted(files):
                    path = os.path.join(dirpath, name)
                    st = os.stat(path)
                    engine._index_single_file(
                        path,
                        name,
                        os.path.splitext(name)[1],
                        st.st_size,
                        FIXED_MTIME_NS,
                        None,
                        respect_standby=False,
                        force_wake=True,
                    )
            for q in load_queries():
                res = engine.search(q["query"], limit=10)
                ranked = []
                for item in res.get("results") or []:
                    p = rel(item.get("canonical_path") or item.get("path") or "")
                    if p not in ranked:
                        ranked.append(p)
                per_query.append({**q, "ranked": ranked[:10], **_metrics(ranked, q["relevant"])})
    finally:
        engine.close()

    def summary(rows):
        n = len(rows) or 1
        return {k: round(sum(r[k] for r in rows) / n, 3) for k in ("recall@1", "recall@5", "mrr@10")} | {
            "queries": len(rows)
        }

    langs = sorted({r["lang"] for r in per_query})
    return {
        "model": model,
        "overall": summary(per_query),
        "by_language": {lang: summary([r for r in per_query if r["lang"] == lang]) for lang in langs},
        "misses": [
            {"id": r["id"], "query": r["query"], "top": r["ranked"][:3]} for r in per_query if not r["recall@5"]
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="zett_lexical_384d")
    ap.add_argument("--dim", type=int, default=None)
    ap.add_argument("--misses", action="store_true", help="list queries whose file wasn't in the top 5")
    args = ap.parse_args()
    out = evaluate(args.model, args.dim)
    if not args.misses:
        out.pop("misses")
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
