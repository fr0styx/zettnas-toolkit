"""A grounding score is shown only when it was measured (AI-1, Batch 0)."""

from backend.services.ai_chat_agent import _grounding_label, _grounding_or_none
from backend.services.rag_grounding import compute_grounding_confidence_score


def test_missing_scores_stay_missing():
    assert _grounding_or_none(None) is None
    assert _grounding_or_none(0) == 0  # a measured zero is kept
    assert _grounding_or_none("72") == 72
    assert _grounding_label(None) == "grounding unverified"
    assert _grounding_label(64) == "64% grounded"


def test_an_answer_with_nothing_to_check_is_not_fully_grounded():
    res = compute_grounding_confidence_score("Ok.", ["The invoice total is 120 EUR."])
    assert res["grounding_confidence_score"] == 0
