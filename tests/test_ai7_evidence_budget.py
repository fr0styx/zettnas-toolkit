"""AI-7: a question puts at most ~2,000 tokens of a person's files in front of the model."""

from backend.services.chat_context import estimate_tokens
from backend.services.chat_synthesis import (
    EVIDENCE_TOKENS,
    _build_structured_llm_context,
    _document_xml,
    cut_to_tokens,
    fit_evidence,
)

SECTION = "The boiler pressure should read between 1.0 and 1.5 bar when cold. " * 120  # ~2,000 tokens


def _cit(i, full=SECTION, excerpt=None):
    return {
        "name": f"file{i}.md",
        "path": f"/mnt/user/docs/file{i}.md",
        "doc_title": f"Document {i}",
        "breadcrumb": "Heating",
        "score": 0.9 - i * 0.05,
        "full_parent_context": full,
        "excerpt": excerpt if excerpt is not None else f"Passage {i} that matched the question. " * 3,
    }


def _rendered(passages):
    return sum(estimate_tokens(_document_xml(i, c, body)) for i, (c, body) in enumerate(passages, start=1))


def test_large_sections_stay_within_the_budget_best_first():
    cits = [_cit(i) for i in range(8)]
    passages = fit_evidence(cits)
    assert _rendered(passages) <= EVIDENCE_TOKENS
    assert [c["name"] for c, _ in passages] == [f"file{i}.md" for i in range(len(passages))]  # rank order kept
    # a section too big to fit gives way to the passage that matched
    assert passages[0][1].startswith("Passage 0 that matched")
    assert len(passages) >= 3


def test_whole_sections_when_they_fit():
    small = "Short section. " * 20
    cits = [_cit(i, full=small) for i in range(3)]
    passages = fit_evidence(cits)
    assert [body for _, body in passages] == [small.strip()] * 3


def test_stops_when_too_little_is_left():
    passages = fit_evidence([_cit(i, full="x " * 900, excerpt="") for i in range(8)], budget=600)
    assert _rendered(passages) <= 600
    assert all(body for _, body in passages)


def test_cutting_ends_at_a_sentence_and_says_so():
    text = "First sentence here. Second sentence follows. " * 200
    out = cut_to_tokens(text, 100)
    assert estimate_tokens(out) <= 110
    assert out.endswith(". …")
    assert cut_to_tokens("short", 100) == "short"


def test_the_prompt_block_respects_the_budget():
    tr = {
        "tool": "search_nas_knowledge",
        "status": "success",
        "citations": [_cit(i) for i in range(8)],
        "grounding_confidence_score": 90,
        "crag_grade": "high",
    }
    block = _build_structured_llm_context([tr])
    start, end = block.index("<retrieved_documents"), block.index("</retrieved_documents>")
    assert estimate_tokens(block[start:end]) <= EVIDENCE_TOKENS + 20  # + the opening tag
    assert "Passage 0 that matched" in block
