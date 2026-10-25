"""AI-11: retrieval quality on a real multilingual corpus can't silently get worse.

tests/rag_eval/baseline.json holds the measured scores of the built-in lexical vectors.
If a change improves them, update the file (python -m tests.rag_eval.run_eval) in the same
commit; if a change lowers any of them by more than 0.01, this test fails.
"""

import json
import os

from tests.rag_eval.run_eval import HERE, answer_matches, evaluate, load_qa, load_queries, write_distractors

TOLERANCE = 0.01


def test_eval_set_shape():
    queries = load_queries()
    assert len(queries) == 200
    assert {q["lang"] for q in queries} == {"en", "de", "zh", "fr", "es"}
    corpus = os.path.join(HERE, "corpus")
    for q in queries:
        for rel in q["relevant"]:
            assert os.path.isfile(os.path.join(corpus, rel)), rel


def test_extended_and_answer_sets_point_at_real_files():
    """AI-3: cross-language and paraphrase queries, and questions with checkable answers."""
    corpus = os.path.join(HERE, "corpus")
    ext = load_queries("extended")
    assert {q["kind"] for q in ext} == {"cross", "paraphrase"}
    assert sum(q["kind"] == "cross" for q in ext) >= 50
    cross_langs = {(q["lang"], q["relevant"][0].split("/")[0]) for q in ext if q["kind"] == "cross"}
    assert all(a != b for a, b in cross_langs), "a cross-language query must ask in another language"
    qa = load_qa()
    assert len(qa) >= 95
    for item in ext + qa:
        for rel in item["relevant"]:
            assert os.path.isfile(os.path.join(corpus, rel)), rel
    for item in qa:
        if item.get("unanswerable"):  # the right answer is that the files don't say (AI-16)
            assert not item["relevant"] and not item["answer_any"]
            continue
        assert item["answer_any"] and all(str(a).strip() for a in item["answer_any"])
    assert sum(1 for item in qa if item.get("unanswerable")) >= 10


def test_answer_scoring_ignores_case_and_spacing():
    assert answer_matches("Bake it at 175 °C for an hour.", ["175"])
    assert answer_matches("Die Nachzahlung beträgt 217,45 EUR", ["217,45", "217.45"])
    assert not answer_matches("I could not find that.", ["4711"])


def test_distractors_are_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_distractors(str(a), 25)
    write_distractors(str(b), 25)
    files = sorted(p.relative_to(a) for p in a.rglob("*.txt"))
    assert len(files) == 25
    assert all((a / f).read_text() == (b / f).read_text() for f in files)


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


def test_extended_retrieval_does_not_regress():
    """The lexical vectors on cross-language and paraphrase queries (low by nature; neural
    models are measured nightly) may not get worse either."""
    with open(os.path.join(HERE, "baseline_extended.json"), encoding="utf-8") as f:
        baseline = json.load(f)
    got = evaluate(which="extended")
    drops = []
    for kind, base in baseline["by_kind"].items():
        now = got["by_kind"][kind]
        for metric in ("recall@1", "recall@5", "mrr@10"):
            if now[metric] < base[metric] - TOLERANCE:
                drops.append(f"{kind} {metric}: {base[metric]} -> {now[metric]}")
    assert not drops, "Retrieval got worse: " + "; ".join(drops)
