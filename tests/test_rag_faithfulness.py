"""The nightly answer eval also checks that answers say only what their sources say (AI-16)."""

from tests.rag_eval.compare import drops
from tests.rag_eval.run_eval import faithfulness


def test_faithfulness_averages_the_apps_own_sentence_check():
    rows = [{"faithful": 100}, {"faithful": 50}, {"faithful": None}, {}]
    assert faithfulness(rows) == {"faithfulness": 0.75, "fully_supported": 0.5, "faithfulness_scored": 2}
    assert faithfulness([{"faithful": None}])["faithfulness"] is None


def test_a_drop_in_faithfulness_fails_the_run():
    base = {"answers": {"accuracy": 0.8, "faithfulness": 0.9, "fully_supported": 0.7}}
    same = {"answers": {"accuracy": 0.8, "faithfulness": 0.89, "fully_supported": 0.7}}
    assert drops(same, base, 0.02) == []
    worse = {"answers": {"accuracy": 0.8, "faithfulness": 0.8, "fully_supported": 0.5}}
    assert drops(worse, base, 0.02) == ["answers faithfulness: 0.9 -> 0.8", "answers fully_supported: 0.7 -> 0.5"]
    # an older baseline without the numbers does not fail a new run
    assert drops(worse, {"answers": {"accuracy": 0.8}}, 0.02) == []
