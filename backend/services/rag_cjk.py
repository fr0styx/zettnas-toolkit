"""A keyword index for Chinese, Japanese and Korean (AI-13).

The main keyword index (rag_chunks_fts, unicode61) keeps a run of CJK characters as one word,
so "红烧肉" in a question never matched "妈妈的红烧肉做法" in a file. This index holds each chunk's
CJK text as overlapping character pairs ("妈妈 妈的 的红 红烧 烧肉 ..."), and a question's CJK
text is looked up the same way; search merges its hits with the main ones.

Only chunks with CJK text get a row. It is contentless (the pairs are not stored twice); a row
goes when its chunk is deleted or its text changes (triggers), and indexing adds rows per file.
"""

from __future__ import annotations

import sqlite3
import time

from backend.services.rag_text import _has_cjk, text_tokens

TABLE = "rag_chunks_cjk"
SCHEMA = (
    f"CREATE VIRTUAL TABLE IF NOT EXISTS {TABLE} USING fts5(grams, content='', contentless_delete=1, tokenize='unicode61')",
    f"CREATE TRIGGER IF NOT EXISTS trg_chunks_cjk_ad AFTER DELETE ON document_chunks BEGIN "
    f"DELETE FROM {TABLE} WHERE rowid = old.chunk_id; END",
    f"CREATE TRIGGER IF NOT EXISTS trg_chunks_cjk_au AFTER UPDATE OF chunk_text ON document_chunks BEGIN "
    f"DELETE FROM {TABLE} WHERE rowid = old.chunk_id; END",
)
MAX_QUERY_GRAMS = 24


def ensure_schema(conn: sqlite3.Connection) -> bool:
    try:
        for sql in SCHEMA:
            conn.execute(sql)
        return True
    except sqlite3.OperationalError:
        return False  # an SQLite without contentless_delete (before 3.43): search works without it


def grams(text: str) -> str:
    """The CJK character pairs of a text, space-separated; '' when it has none."""
    if not _has_cjk(text):
        return ""
    return " ".join(t for t in text_tokens((text or "").lower()) if _has_cjk(t))


def _put(conn: sqlite3.Connection, rows: list[tuple[int, str]]) -> int:
    n = 0
    for cid, g in rows:
        conn.execute(f"DELETE FROM {TABLE} WHERE rowid = ?", (cid,))
        if g:
            conn.execute(f"INSERT INTO {TABLE} (rowid, grams) VALUES (?, ?)", (cid, g))
            n += 1
    return n


def sync_file(conn: sqlite3.Connection, file_id: int) -> int:
    """Adds the rows for one file's chunks, after indexing wrote them."""
    try:
        rows = conn.execute(
            "SELECT chunk_id, file_name, heading_context, chunk_text FROM document_chunks "
            "WHERE file_id = ? AND chunk_level != 'parent'",
            (file_id,),
        ).fetchall()
        return _put(conn, [(int(r[0]), grams(f"{r[1] or ''} {r[2] or ''} {r[3] or ''}")) for r in rows])
    except sqlite3.OperationalError:
        return 0  # no index table (old SQLite)


def backfill(conn: sqlite3.Connection) -> int:
    """Once per index: rows for the chunks indexed before this table existed (no disk access)."""
    conn.execute("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)")
    if conn.execute("SELECT 1 FROM rag_meta WHERE key = 'cjk_fts_v1'").fetchone():
        return 0
    if not ensure_schema(conn):
        return 0
    rows = []
    for r in conn.execute(
        "SELECT chunk_id, file_name, heading_context, chunk_text FROM document_chunks WHERE chunk_level != 'parent'"
    ):
        g = grams(f"{r[1] or ''} {r[2] or ''} {r[3] or ''}")
        if g:
            rows.append((int(r[0]), g))
    n = _put(conn, rows)
    conn.execute("INSERT OR REPLACE INTO rag_meta (key, value) VALUES ('cjk_fts_v1', ?)", (str(time.time()),))
    conn.commit()
    return n


def match_query(question: str) -> str:
    """The MATCH expression for a question's CJK text: its character pairs, any of them; '' when
    the question has no CJK text."""
    seen: list[str] = []
    for g in grams(question).split():
        if g not in seen:
            seen.append(g)
    return " OR ".join(f'"{g}"' for g in seen[:MAX_QUERY_GRAMS])
