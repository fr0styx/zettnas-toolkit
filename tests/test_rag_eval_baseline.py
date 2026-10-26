"""AI-11: retrieval quality on a real multilingual corpus can't silently get worse.

tests/rag_eval/baseline.json holds the measured scores of the built-in lexical vectors.
If a change improves them, update the file (python -m tests.rag_eval.run_eval) in the same
commit; if a change lowers any of them by more than 0.01, this test fails.
"""

import json
import os
import sys

import pytest

from tests.rag_eval import documents
from tests.rag_eval.run_eval import (
    HERE,
    answer_matches,
    evaluate,
    load_qa,
    load_queries,
    split_of,
    write_distractors,
)

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
    # multi-hop: every required part, and one of the accepted ones
    assert answer_matches("The repair cost 583.20, under the 650 planned.", [], ["583", "650"])
    assert not answer_matches("The repair cost 583.20.", [], ["583", "650"])
    assert answer_matches("About 1010 a year against 1100 planned.", ["1010", "1 010"], ["1100"])


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
    scopes = [("overall", baseline["overall"], got["overall"])]
    scopes += [(lang, b, got["by_language"][lang]) for lang, b in baseline["by_language"].items()]
    scopes += [(f"{s} split", b, got["by_split"][s]) for s, b in baseline.get("by_split", {}).items()]
    for scope, base, now in scopes:
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


# --- AI-16: long, Office and scanned documents, multi-hop questions, a held-out split ----------


def test_the_document_set_is_the_same_every_run_and_covers_each_kind(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    written = documents.build(str(a))
    documents.build(str(b))
    assert all((a / f).read_bytes() == (b / f).read_bytes() for f in written)
    queries, qa = load_queries("documents"), load_qa("documents")
    kinds = {q["kind"] for q in queries}
    assert kinds == {"long", "office", "scanned", "multihop"}
    assert {q["kind"] for q in qa} == kinds
    for item in queries + qa:
        assert item["relevant"] and all(r in written for r in item["relevant"]), item["id"]
        if item["kind"] == "multihop":
            assert len(item["relevant"]) == 2
    for item in qa:
        assert item["answer_any"] or item.get("answer_all"), item["id"]
    # scanned files have no text of their own: only the vision model (or its stand-in) reads them
    from backend.services.rag_documents import extract_document_text

    for rel in documents.SCANNED:
        if rel.endswith(".pdf"):
            assert not extract_document_text(str(a / rel), ".pdf").strip()


def test_document_retrieval_does_not_regress():
    with open(os.path.join(HERE, "baseline_documents.json"), encoding="utf-8") as f:
        baseline = json.load(f)
    got = evaluate(which="documents")
    # every photo and scanned PDF went through the vision queue and became searchable text
    assert got["scanned_read"].get("done") == len(documents.SCANNED)
    drops = []
    scopes = [(f"kind {k}", b, got["by_kind"][k]) for k, b in baseline["by_kind"].items()]
    scopes += [(f"{s} split", b, got["by_split"][s]) for s, b in baseline["by_split"].items()]
    for scope, base, now in scopes:
        for metric in ("recall@1", "recall@5", "all@5", "mrr@10"):
            if now[metric] < base[metric] - TOLERANCE:
                drops.append(f"{scope} {metric}: {base[metric]} -> {now[metric]}")
    assert not drops, "Retrieval got worse: " + "; ".join(drops)


def test_one_question_in_five_is_held_out_and_stays_so():
    items = load_queries("all") + load_queries("documents") + load_qa() + load_qa("documents")
    held = [i for i in items if i["split"] == "heldout"]
    assert 0.15 <= len(held) / len(items) <= 0.25
    for name in ("base", "extended", "documents"):
        assert {q["split"] for q in load_queries(name)} == {"dev", "heldout"}, name
    # fixed by the id alone: adding or reordering questions moves nobody between splits
    assert split_of("doc-030") == "heldout" and split_of("doc-031") == "dev"


SPEED_DISTRACTORS = 500
SPEED_SLACK = 1.5  # machines differ in more than raw speed; a real slowdown is far larger


def _traced() -> bool:
    """Coverage (or a debugger) is watching: it slows the search far more than the yardstick."""
    if sys.gettrace() is not None:
        return True
    mon = getattr(sys, "monitoring", None)
    return bool(mon and mon.get_tool(mon.COVERAGE_ID))


@pytest.mark.skipif(_traced(), reason="timed without coverage, in its own CI step")
def test_search_stays_fast():
    """Search time over 540 files, in units of a fixed piece of work timed on the same machine
    (AI-16): it may not grow by half. Re-record baseline_speed.json only for an intended change.
    CI runs it on its own, without coverage (.github/workflows/ci.yml, "Search speed")."""
    with open(os.path.join(HERE, "baseline_speed.json"), encoding="utf-8") as f:
        baseline = json.load(f)
    got = evaluate(distractors=SPEED_DISTRACTORS)["latency"]
    print(f"search p95: {got['p95_units']} units")  # CI shows it; the baseline comes from GitHub's runners
    assert got["p95_units"] <= baseline["p95_units"] * SPEED_SLACK, (
        f"search p95 went from {baseline['p95_units']} to {got['p95_units']} units "
        f"({got['p95_ms']} ms here, a unit is {got['unit_ms']} ms)"
    )
