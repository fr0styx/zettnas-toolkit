"""AI-21: PDFs printed by Chrome (the "Save as PDF" most people use) come out as text in the right
order, umlauts, euro signs and Chinese intact, and each line knows its page."""

import os

import pytest

from backend.services.rag_documents import extract_document_text, page_of, page_starts

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pdf")


@pytest.mark.parametrize(
    "name, words, second_page",
    [
        (
            "de-chrome.pdf",
            ["Nebenkostenabrechnung", "Lindenstraße", "184,50 €", "fällig", "Rückerstattung"],
            "Ablesewerte",
        ),
        ("zh-chrome.pdf", ["租房合同摘要", "王先生", "三千五百元", "全额退还"], "维修条款"),
    ],
)
def test_chrome_pdfs_index_real_text_by_page(name, words, second_page):
    text = extract_document_text(os.path.join(FIXTURES, name), ".pdf")
    for w in words:
        assert w in text, (name, w, text[:200])
    assert text.index(words[0]) < text.index(words[-1])  # reading order kept
    lines = text.split("\n")
    starts = page_starts(text)
    first = next(i for i, line in enumerate(lines) if words[0] in line)
    second = next(i for i, line in enumerate(lines) if second_page in line)
    assert page_of(first + 1, starts) == 1 and page_of(second + 1, starts) == 2
