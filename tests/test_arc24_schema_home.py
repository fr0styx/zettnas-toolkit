"""ARC-24: each database's tables are defined in its schema module, not wherever they are used."""

import io
import pathlib
import re
import tokenize

from backend import db
from backend.services import rag_schema

HOMES = {
    "backend/db.py",  # history.db
    "backend/users_db.py",  # users.db
    "backend/services/ai_conversations_db.py",  # ai_conversations.db
    "backend/services/rag_schema.py",  # rag_index.db
    "backend/db_schema.py",  # migrations
}
CREATE = re.compile(r"CREATE\s+(VIRTUAL\s+)?(TABLE|INDEX|TRIGGER)", re.I)


def creates(src: str) -> bool:
    """A string literal (not a comment) with DDL in it."""
    return any(
        tok.type == tokenize.STRING and CREATE.search(tok.string)
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
    )


def test_no_module_outside_the_schema_homes_creates_tables():
    stray = [
        str(p)
        for p in sorted(pathlib.Path("backend").rglob("*.py"))
        if str(p) not in HOMES and creates(p.read_text(encoding="utf-8"))
    ]
    assert stray == [], f"define the table in its database's schema module: {stray}"


def test_the_ai_index_schema_builds_on_an_empty_database(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "rag.db")
    conn.executescript(rag_schema.INDEX)
    for sql in (*rag_schema.TAGS, rag_schema.META, rag_schema.REEMBED_STAGING):
        conn.execute(sql)
    conn.executescript(rag_schema.PHOTO_SEMANTIC)
    conn.executescript(rag_schema.VISION)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "indexed_files",
        "document_chunks",
        "doc_tags",
        "rag_meta",
        "reembed_staging",
        "photo_semantic",
        "photo_vision",
        "pdf_ocr",
    } <= names
    assert "vec0(chunk_id INTEGER PRIMARY KEY, embedding int8[384]" in rag_schema.vec0("vec_int8_384", 384)


def test_ai_requests_is_created_with_the_history_tables(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "h.db")
    for sql in db.AI_REQUESTS_SCHEMA:
        conn.execute(sql)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'idx_ai_requests_ts'").fetchone()
