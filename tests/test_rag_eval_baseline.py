"""AI-11: retrieval quality on a real multilingual corpus can't silently get worse.

tests/rag_eval/baseline.json holds the measured scores of the built-in lexical vectors.
If a change improves them, update the file (python -m tests.rag_eval.run_eval) in the same
commit; if a change lowers any of them by more than 0.01, this test fails.
"""

import json
import os

from tests.rag_eval.run_eval import HERE, evaluate, load_queries

TOLERANCE = 0.01


def test_eval_set_shape():
    queries = load_queries()
    assert len(queries) == 200
    assert {q["lang"] for q in queries} == {"en", "de", "zh", "fr", "es"}
    corpus = os.path.join(HERE, "corpus")
    for q in queries:
        for rel in q["relevant"]:
            assert os.path.isfile(os.path.join(corpus, rel)), rel


def test_retrieval_does_not_regress():
    with open(os.path.join(HERE, "baseline.json"), encoding="utf-8") as f:
        baseline = json.load(f)
    got = evaluate()
    drops = []
    for scope, base in [("overall", baseline["overall"])] + list(baseline["by_language"].items()):
        now = got["overall"] if scope == "overall" else got["by_language"][scope]
        for metric in ("recall@1", "recall@5", "mrr@10"):
            if now[metric] < base[metric] - TOLERANCE:
                drops.append(f"{scope} {metric}: {base[metric]} -> {now[metric]}")
    assert not drops, "Retrieval got worse: " + "; ".join(drops)
