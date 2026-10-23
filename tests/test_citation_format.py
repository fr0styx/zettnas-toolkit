"""Answers use one citation style, and only cite sources that exist (AI-3, Batch 0)."""

from backend.services.ai_chat_agent import tidy_citations


def test_doc_markers_become_numbers():
    assert tidy_citations("Net 30 [Doc 1] and [document 2].", 2) == "Net 30 [1] and [2]."


def test_citations_without_a_source_are_dropped():
    assert tidy_citations("Paid [1] late [7].", 2) == "Paid [1] late."


def test_code_and_links_are_left_alone():
    text = "See [2](https://example.com)\n```\narr[9] = 1\n```"
    assert tidy_citations(text, 1) == text


def test_numbers_are_kept_when_there_are_no_sources():
    assert tidy_citations("Step [3] done.", 0) == "Step [3] done."
