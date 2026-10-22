"""AI-13: Unicode tokenisation, and the one-time re-learn of files the old tokeniser missed."""

import time

from backend.services import rag_engine as re_


def test_cjk_runs_become_bigrams_latin_stays_whole():
    assert re_.text_tokens("红烧肉怎么做") == ["红烧", "烧肉", "肉怎", "怎么", "么做"]
    assert re_.text_tokens("zfs pool größe") == ["zfs", "pool", "größe"]
    assert re_.text_tokens("单") == ["单"]
    assert re_.text_tokens("Привет мир".lower()) == ["привет", "мир"]


def test_cjk_keyword_match_has_no_word_boundaries():
    assert re_._token_matches_word("红烧", "妈妈的红烧肉做法")
    assert not re_._token_matches_word("car", "cards")


def test_migration_relearns_only_files_with_cjk_text(tmp_path):
    eng = re_.RagSearchEngine(db_path=str(tmp_path / "r.db"))
    eng._ensure_schema()
    conn = eng._get_conn(readonly=False)
    try:
        conn.execute("DELETE FROM rag_meta")
        for fid, path, text in ((1, "/a.md", "Boiler service notes"), (2, "/b.md", "空调保养记录")):
            conn.execute(
                "INSERT INTO indexed_files (file_id, canonical_path, parent_dir, file_name, file_ext, modality,"
                " size_bytes, mtime_ns, sha256_hash, indexed_at, last_verified_at, index_version)"
                " VALUES (?, ?, '/', ?, '.md', 'document', 1, 1, 'x', ?, ?, ?)",
                (fid, path, path[1:], time.time(), time.time(), re_.CURRENT_INDEX_VERSION),
            )
            conn.execute(
                "INSERT INTO document_chunks (file_id, chunk_index, chunk_level, source_modality, file_name, doc_type,"
                " heading_context, structural_context, chunk_text, raw_chunk_text, doc_metadata_json, line_start,"
                " line_end, token_count, embedding_f32) VALUES (?, 0, 'child', 'text', ?, 'generic', '', '', ?, ?,"
                " '{}', 1, 1, 3, X'00')",
                (fid, path[1:], text, text),
            )
        conn.commit()
        assert eng._migrate_unicode_tokens(conn) == 1
        versions = dict(conn.execute("SELECT file_id, index_version FROM indexed_files").fetchall())
        assert versions == {1: re_.CURRENT_INDEX_VERSION, 2: 0}
        assert eng._migrate_unicode_tokens(conn) == 0  # only once
    finally:
        conn.close()
