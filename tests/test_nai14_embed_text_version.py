"""NAI-14: a keyword-only index that later gets an embedder, and a flushed index, are recorded as
embedded the current way, so they are never re-embedded at night for nothing."""

from backend.services import rag_engine as re_mod


def _db(neural_model=None):
    conn = re_mod.sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, embedding_model TEXT, chunk_level TEXT)")
    if neural_model is not None:
        conn.execute("INSERT INTO document_chunks (embedding_model, chunk_level) VALUES (?, 'child')", (neural_model,))
    return conn


def _recorded(conn):
    try:
        row = conn.execute("SELECT value FROM rag_meta WHERE key = 'embed_text_version'").fetchone()
    except re_mod.sqlite3.Error:
        return None
    return int(row[0]) if row else None


def test_a_keyword_only_index_is_stamped():
    conn = _db("zettnas-unified-384-v2")
    re_mod.stamp_new_index(conn)
    assert _recorded(conn) == re_mod.EMBED_TEXT_VERSION
    # an embedder turned on later writes current vectors: the record still holds
    conn.execute("INSERT INTO document_chunks (embedding_model, chunk_level) VALUES ('eg2', 'child')")
    assert re_mod.read_embed_text_version(conn) == re_mod.EMBED_TEXT_VERSION


def test_an_index_with_old_neural_vectors_is_not():
    conn = _db("eg2")
    re_mod.stamp_new_index(conn)
    assert _recorded(conn) is None and re_mod.read_embed_text_version(conn) == 1


def test_an_empty_index_is_stamped():
    conn = _db()
    re_mod.stamp_new_index(conn)
    assert _recorded(conn) == re_mod.EMBED_TEXT_VERSION


def test_the_flush_records_it():
    import inspect

    from backend.services import rag_engine_indexing

    src = inspect.getsource(rag_engine_indexing.RagIndexingMixin.flush_index)
    assert "set_embed_text_version(conn, _core().EMBED_TEXT_VERSION)" in src
