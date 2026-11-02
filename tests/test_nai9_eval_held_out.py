"""NAI-9: an eval that can't flatter the ranking. Questions are held out by file, and a hard mode
indexes the corpus under names that say nothing, beside near-topic files in the same language."""

import json
import os
import tempfile

import pytest

from tests.rag_eval.run_eval import (
    CORPUS,
    HARD_PER_FILE,
    HERE,
    doc_of,
    evaluate,
    load_qa,
    load_queries,
    topic_of,
    write_hard_distractors,
    write_neutral_copy,
)

pytestmark = pytest.mark.usefixtures("search_as_system")

TOLERANCE = 0.01


def _corpus_files() -> list[str]:
    return sorted(
        os.path.relpath(os.path.join(d, f), CORPUS).replace(os.sep, "/") for d, _, fs in os.walk(CORPUS) for f in fs
    )


def test_a_held_out_file_has_no_dev_questions():
    items = load_queries("all") + load_qa()
    held = {doc_of(i) for i in items if i["split"] == "heldout" and i.get("relevant")}
    assert held, "some files are held out"
    for i in items:
        if i["split"] == "dev" and len(i.get("relevant") or []) == 1:
            assert i["relevant"][0] not in held, i["id"]
    assert doc_of({"id": "q1", "relevant": ["b.md", "a.md"]}) == "a.md"
    assert doc_of({"id": "q2", "relevant": []}) == "q2"


def test_neutral_copy_hides_the_topic_and_maps_back():
    with tempfile.TemporaryDirectory() as tmp:
        names = write_neutral_copy(CORPUS, tmp)
        assert sorted(names.values()) == _corpus_files()
        for path, rel in names.items():
            base = os.path.basename(path).lower()
            assert not any(w.lower() in base for w in topic_of(rel).split() if len(w) > 2), (base, rel)
            assert os.path.splitext(path)[1] == os.path.splitext(rel)[1]
            with open(path, "rb") as a, open(os.path.join(CORPUS, rel), "rb") as b:
                assert a.read() == b.read()


def test_hard_distractors_share_topic_and_language():
    with tempfile.TemporaryDirectory() as tmp:
        n = write_hard_distractors(CORPUS, tmp)
        files = _corpus_files()
        assert n == HARD_PER_FILE * len(files)
        rel = "en/recipes/banana_bread.md"
        near = sorted(f for f in os.listdir(os.path.join(tmp, "en", "recipes")) if f.startswith("banana_bread_"))
        assert len(near) == HARD_PER_FILE
        with open(os.path.join(tmp, "en", "recipes", near[0]), encoding="utf-8") as f:
            assert topic_of(rel) in f.read()
        assert topic_of("zh/食谱/红烧肉.md") == "红烧肉" and topic_of("de/a/router_neustart.sh") == "router neustart"


def test_hard_mode_does_not_regress():
    """The built-in vectors on names that say nothing, among near-topic files. If a change lifts
    these scores, update tests/rag_eval/baseline_hard.json in the same commit."""
    with open(os.path.join(HERE, "baseline_hard.json"), encoding="utf-8") as f:
        baseline = json.load(f)
    got = evaluate(which="base", neutral_names=True, hard_distractors=True)
    assert got["neutral_names"] and got["hard_distractors"] == baseline["hard_distractors"]
    drops = []
    scopes = [("overall", baseline["overall"], got["overall"])]
    scopes += [(f"lang {k}", b, got["by_language"][k]) for k, b in baseline["by_language"].items()]
    scopes += [(f"{s} split", b, got["by_split"][s]) for s, b in baseline["by_split"].items()]
    for scope, base, now in scopes:
        for metric in ("recall@1", "recall@5", "mrr@10"):
            if now[metric] < base[metric] - TOLERANCE:
                drops.append(f"{scope} {metric}: {base[metric]} -> {now[metric]}")
    assert not drops, "Retrieval got worse: " + "; ".join(drops)
