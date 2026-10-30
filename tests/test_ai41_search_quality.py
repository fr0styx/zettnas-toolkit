"""AI-41: search as accurate and fast as DigUp's with the same EmbeddingGemma 2.

What was wrong: every chunk was embedded with its "[Folder: .. | Doc: ..]" breadcrumb (all chunks
looked alike), natural questions got the code prompt, a fragment-matching rerank decided the order
of neural results, keywords had almost no say, and each search opened a cold encrypted connection
and joined the full-text index before ranking it.
"""

import asyncio
import os
import shutil
import sqlite3
import struct
import threading
import time

import pytest

from backend.services import rag_engine as re_mod
from backend.services import rag_engine_search as rs
from backend.services.rag_embeddings import (
    TASK_PREFIX_CODE,
    TASK_PREFIX_SEARCH,
    chunk_embedding_text,
    classify_query_task_intent,
)
from backend.services.rag_engine import RagSearchEngine

# --- what a chunk is embedded as ---------------------------------------------------------------


def test_a_chunk_is_embedded_without_its_breadcrumb():
    chunk = {
        "heading_context": "Ostsee-Urlaub im August",
        "chunk_text": "[Folder: reisen | Doc: Ostsee-Urlaub im August]\nFerienwohnung in Kühlungsborn",
        "raw_chunk_text": "Ferienwohnung in Kühlungsborn",
    }
    text = chunk_embedding_text("Ostsee-Urlaub im August", "ostsee_urlaub.html", chunk, ".html")
    assert text == "title: Ostsee-Urlaub im August | text: Ferienwohnung in Kühlungsborn"
    assert "[Folder" not in text


def test_the_title_is_the_file_name_without_its_extension_and_a_new_heading_is_added():
    chunk = {"heading_context": "Car insurance", "raw_chunk_text": "renewal 412 GBP"}
    assert chunk_embedding_text(None, "2025_household_budget.csv", chunk) == (
        "title: 2025_household_budget > Car insurance | text: renewal 412 GBP"
    )
    assert chunk_embedding_text("budget.csv", "budget.csv", {"chunk_text": "x"}) == "title: budget | text: x"
    assert chunk_embedding_text("", "", {"raw_chunk_text": "x"}) == "title: none | text: x"


# --- which prompt a query gets -------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "where did we stay in the old imperial capital",
        "flights from London to Kyoto",
        "let me see the lease",
        "select photos from last summer",
        "class photos of the kids",
        "return policy for the washing machine",
        "public holidays 2025",
        # copy suffixes, arrows and lists households type (NAI-15)
        "Scan(1)",
        "Rechnung(2).pdf",
        "IMG_2034(3)",
        "Berlin -> Paris",
        "tickets; hotel",
    ],
)
def test_questions_that_contain_code_words_are_searches(query):
    assert classify_query_task_intent(query)[1] != TASK_PREFIX_CODE


@pytest.mark.parametrize(
    "query",
    [
        "def resolve_backing_disk(path):",
        "select * from logs where level = 'error'",
        "SELECT * FROM container_stats",
        "const retries = 5",
        "import os",
        "useEffect(() => {})",
        "foo::bar",
        "btrfs subvol snapshot /mnt/user/share",
        "the backup_photos.py script",
        "parse(line); return",
        "node -> next; free(node)",
        "main()",
    ],
)
def test_code_keeps_the_code_prompt(query):
    assert classify_query_task_intent(query)[1] == TASK_PREFIX_CODE


def test_a_plain_search_gets_the_search_prompt():
    assert classify_query_task_intent("car insurance renewal")[1] == TASK_PREFIX_SEARCH


# --- ranking ---------------------------------------------------------------------------------------


def test_coverage_counts_meaningful_words_in_every_language():
    terms = rs.coverage_terms(["did", "we", "pay", "der", "el", "car", "insurance"])
    assert terms == ["pay", "car", "insurance"]
    assert rs.keyword_coverage(terms, "car insurance renewal 412") == pytest.approx(2 / 3)
    assert rs.keyword_coverage([], "anything") == 0.0


def test_the_spread_of_a_query_over_the_index():
    q = [1.0, 0.0]
    same = [[1.0, 0.0]] * 30
    assert rs.similarity_spread(q, same) == rs.SPREAD_FLOOR  # no spread: the floor
    mixed = [[1.0, 0.0]] * 15 + [[0.0, 1.0]] * 15
    assert rs.similarity_spread(q, mixed) == pytest.approx(0.5)
    assert rs.similarity_spread(q, mixed[:5]) == rs.SPREAD_FLOOR  # too few to tell


def test_neural_results_keep_their_order_and_keyword_vectors_get_the_late_pass(monkeypatch):
    items = [{"score": 0.6, "name": "b"}, {"score": 0.7, "name": "a"}]
    called = []
    monkeypatch.setattr(rs, "late_interaction_rerank", lambda q, c, top_k: called.append(top_k) or c[:top_k])
    out = rs.order_by_relevance("q", list(items), 10, "embeddinggemma-2-ov")
    assert [i["name"] for i in out] == ["a", "b"] and not called
    rs.order_by_relevance("q", list(items), 10, "zett_lexical_384d")
    assert called == [10]


# --- the keyword candidates ------------------------------------------------------------------------


@pytest.fixture
def fts():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE indexed_files (file_id INTEGER PRIMARY KEY, share TEXT);
        CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, file_id INTEGER);
        CREATE VIRTUAL TABLE docs_fts USING fts5(body);
        """
    )
    for i in range(1, 41):
        share = "kids" if i % 4 == 0 else "family"
        conn.execute("INSERT INTO indexed_files VALUES (?, ?)", (i, share))
        conn.execute("INSERT INTO document_chunks VALUES (?, ?)", (i, i))
        conn.execute("INSERT INTO docs_fts(rowid, body) VALUES (?, ?)", (i, "invoice " * (1 + i % 5)))
    return conn


def test_keyword_hits_keep_to_the_scope(fts):
    hits = rs.keyword_top(fts, "docs_fts", "-bm25(docs_fts)", "invoice", "f.share = ?", ["kids"])
    assert hits and all(cid % 4 == 0 for cid, _ in hits)
    assert [s for _, s in hits] == sorted((s for _, s in hits), reverse=True)


def test_a_small_scope_below_the_pool_is_found_by_the_joined_query(fts, monkeypatch):
    monkeypatch.setattr(rs, "KEYWORD_POOL", 5)  # the pool holds no "kids" chunk ...
    monkeypatch.setattr(rs, "KEYWORD_TOP", 3)
    hits = rs.keyword_top(fts, "docs_fts", "-bm25(docs_fts)", "invoice", "f.share = ?", ["kids"])
    assert len(hits) == 3 and all(cid % 4 == 0 for cid, _ in hits)  # ... the joined query finds them
    assert rs.keyword_top(fts, "docs_fts", "-bm25(docs_fts)", "nothing", "1 = 1", []) == []


# --- the warm read connection ----------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(re_mod, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = RagSearchEngine(db_path=str(tmp_path / "rag_index.db"))
    eng.update_config({"embedding_model": "eg2", "embedding_dim": 4})
    yield eng
    eng.close()


def test_searches_share_one_warm_connection(engine):
    a = engine._search_conn()
    assert isinstance(a, re_mod._LentConnection)
    cur = a.execute("SELECT 1 UNION SELECT 2")
    cur.fetchone()  # left unfinished
    b = engine._search_conn()  # lent out: a fresh one
    assert not isinstance(b, re_mod._LentConnection)
    b.close()
    a.close()
    with pytest.raises(re_mod.sqlite3.ProgrammingError):
        cur.fetchone()  # given back with its cursors closed: no read snapshot is kept
    c = engine._search_conn()
    assert c._conn is a._conn  # the same warm connection
    assert int(c.execute("PRAGMA cache_size").fetchone()[0]) <= -re_mod.READ_CACHE_KIB
    c.close()


def test_the_warm_connection_is_opened_again_for_a_new_index_file(engine, tmp_path):
    first = engine._search_conn()
    inner = first._conn
    first.close()
    copy = tmp_path / "copy.db"
    shutil.copy(engine.db_path, copy)
    os.replace(copy, engine.db_path)  # a rebuild or restore puts a new file in place
    again = engine._search_conn()
    assert again._conn is not inner
    again.close()


def test_the_warm_cache_holds_the_vectors(engine):
    conn = engine._get_conn(readonly=True)
    try:
        assert re_mod.warm_cache_kib(conn, engine) == re_mod.READ_CACHE_KIB  # empty index: the usual cache
    finally:
        conn.close()

    class Fake:
        def execute(self, sql):
            return self

        def fetchone(self):
            return (200_000,)

    engine._vec_table_dim = 768
    assert re_mod.warm_cache_kib(Fake(), engine) == int(200_000 * 768 * 1.25 / 1024)
    assert re_mod.warm_cache_kib(type("Huge", (Fake,), {"fetchone": lambda s: (10**9,)})(), engine) == (
        re_mod.WARM_CACHE_MAX_KIB
    )


# --- the nightly re-embed as clean text --------------------------------------------------------------


def _add_chunks(eng, model):
    conn = eng._get_conn(readonly=False)
    path = f"/mnt/user/docs/{model}/a.txt"
    cur = conn.execute(
        """INSERT INTO indexed_files (canonical_path, parent_dir, file_name, file_ext, modality, doc_type,
           size_bytes, mtime_ns, sha256_hash, embedding_model, chunk_count, indexed_at, last_verified_at)
           VALUES (?, '/mnt/user/docs', 'a.txt', '.txt', 'document', 'generic',
           10, 1, 'h', ?, 1, 1, 1)""",
        (path, model),
    )
    conn.execute(
        """INSERT INTO document_chunks (file_id, chunk_index, chunk_text, raw_chunk_text, heading_context,
           embedding_f32, embedding_model, embedding_dim) VALUES (?, 0, '[Folder: docs | Doc: Intro]\nhello', 'hello',
           'Intro', ?, ?, 4)""",
        (cur.lastrowid, struct.pack("<4f", 1, 0, 0, 0), model),
    )
    conn.execute("DELETE FROM rag_meta WHERE key = 'embed_text_version'")
    conn.commit()
    conn.close()


def test_a_new_index_is_current_and_an_old_one_is_not(engine):
    assert engine.embed_text_version() == re_mod.EMBED_TEXT_VERSION  # created empty: stamped
    _add_chunks(engine, "zettnas-unified-384-v2")
    assert engine.embed_text_version() == re_mod.EMBED_TEXT_VERSION  # keyword vectors: nothing to do
    _add_chunks(engine, "eg2")
    assert engine.embed_text_version() == 1  # neural vectors from before AI-41


def test_the_upgrade_re_embeds_every_chunk_as_clean_text(engine, monkeypatch):
    _add_chunks(engine, "eg2")
    monkeypatch.setattr(engine, "_write_reindex_progress", lambda data: None)
    seen = []

    def vectors(texts, model, target_dim=None, host=None, batch_size=16):
        seen.extend(texts)
        return [struct.pack("<4f", 0, 1, 0, 0) for _ in texts]

    monkeypatch.setattr(re_mod, "compute_neural_embeddings_batch", vectors)
    monkeypatch.setattr("backend.services.rag_engine_learning.upgrade_window_open", lambda: True)
    assert engine._maybe_upgrade_embedding_text() is True
    engine._text_upgrade_thread.join(30)
    assert engine.text_upgrade_progress["status"] == "complete"
    assert seen == ["title: a > Intro | text: hello"]
    assert engine.embed_text_version() == re_mod.EMBED_TEXT_VERSION
    assert engine._maybe_upgrade_embedding_text() is False  # done once


def test_the_upgrade_waits_for_the_night_and_a_neural_model(engine, monkeypatch):
    _add_chunks(engine, "eg2")
    monkeypatch.setattr("backend.services.rag_engine_learning.upgrade_window_open", lambda: False)
    assert engine._maybe_upgrade_embedding_text() is False
    monkeypatch.setattr("backend.services.rag_engine_learning.upgrade_window_open", lambda: True)
    engine.update_config({"embedding_model": "zett_lexical_384d"})
    assert engine._maybe_upgrade_embedding_text() is False


def test_one_re_embed_at_a_time(engine):
    engine._reembed_lock.acquire()
    try:
        res = asyncio.run(engine.in_place_reembed_collection("eg2", 4))
    finally:
        engine._reembed_lock.release()
    assert res["status"] == "busy"


def test_the_settings_page_sees_the_nightly_re_embed(engine, monkeypatch):
    from backend.services import rag_reindex_status as st

    monkeypatch.setattr(st, "get_rag_engine", lambda: engine)
    monkeypatch.setattr(st, "_REINDEX_CACHE", {})
    monkeypatch.setattr(st, "_REINDEX_CACHE_TIME", 0.0)
    engine.text_upgrade_progress = {"status": "running", "completed": 3, "total": 10, "reason": "embedding_text"}
    got = st.get_reindex_status()
    assert got["status"] == "running" and got["reason"] == "embedding_text"


def test_the_spread_sample_is_read_once(engine):
    _add_chunks(engine, "eg2")
    conn = engine._get_conn(readonly=True)
    try:
        first = engine._spread_sample(conn, "eg2")
        assert len(first) == 1 and engine._spread_sample(conn, "eg2") is first  # kept
        engine._spread_cache = ("eg2", time.time() - rs.SPREAD_SAMPLE_SECS - 1, first)
        assert engine._spread_sample(conn, "eg2") is not first  # stale: read again
        assert engine._spread_sample(conn, "other-model") == []  # another model's vectors aren't used
    finally:
        conn.close()


def test_lending_is_thread_safe(engine):
    lent = []

    def grab():
        c = engine._search_conn()
        lent.append(isinstance(c, re_mod._LentConnection))
        time.sleep(0.05)
        c.close()

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert lent.count(True) >= 1 and len(lent) == 4


def test_an_index_without_tables_needs_no_upgrade():
    assert re_mod.read_embed_text_version(re_mod.sqlite3.connect(":memory:")) == re_mod.EMBED_TEXT_VERSION
