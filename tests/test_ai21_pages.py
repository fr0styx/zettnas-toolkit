"""AI-21: a passage from a PDF knows its page, and citations carry it."""

import sqlite3

from backend.db_schema import ensure_columns
from backend.services import rag_documents
from backend.services.chat_synthesis import _document_xml
from backend.services.rag_documents import page_of, page_starts


def test_pages_follow_the_form_feeds():
    text = "one\n\f\ntwo a\ntwo b\n\f\n\n\f\nfour"  # page 3 is empty and still counts
    starts = page_starts(text)
    lines = text.split("\n")
    assert [page_of(lines.index(w) + 1, starts) for w in ("one", "two a", "two b", "four")] == [1, 2, 2, 4]


def test_chunk_lines_count_from_the_extracted_text():
    pages = [
        f"Section {i}\n" + "\n".join(f"Line {i}.{j} of the lease about rent and repairs." for j in range(40))
        for i in range(1, 4)
    ]
    text = "\n\f\n".join(pages)
    _t, _title, _meta, children, _parents = rag_documents.generate_contextual_hierarchical_chunks(
        "lease.pdf", ".pdf", text, "/x/lease.pdf"
    )
    starts = page_starts(text)
    lines = text.split("\n")
    for ch in children:
        first = lines[int(ch["line_start"]) - 1]
        assert first.strip() and first != "\f"
        page = page_of(int(ch["line_start"]), starts)
        assert f"Line {page}." in first or f"Section {page}" in first, (page, first)


def test_old_indexes_get_the_column():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, line_end INTEGER)")
    assert "document_chunks.page" in ensure_columns(conn, "rag_index.db")
    assert conn.execute("SELECT page FROM document_chunks").fetchall() == []


def test_the_model_sees_the_page():
    c = {"name": "lease.pdf", "path": "/x/lease.pdf", "line_start": 3, "line_end": 9, "page": 4}
    assert ' page="4"' in _document_xml(1, c, "rent")
    assert "page=" not in _document_xml(1, {**c, "page": 0}, "rent")
