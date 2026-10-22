"""AI-20: a folder can be forgotten by the index, and old conversations expire."""

import time

from backend.services import ai_conversations_db as convs


def test_forget_folder_removes_its_data_and_excludes_it(tmp_path, monkeypatch):
    from backend.services.rag_engine import get_rag_engine

    rag = get_rag_engine()
    rag._ensure_schema()
    conn = rag._get_conn(readonly=False)
    try:
        for path in ("/mnt/user/secret/a.txt", "/mnt/user/secret/sub/b.txt", "/mnt/user/secretive/c.txt"):
            conn.execute(
                "INSERT OR REPLACE INTO indexed_files (canonical_path, parent_dir, file_name, file_ext, modality,"
                " size_bytes, mtime_ns, sha256_hash, indexed_at, last_verified_at)"
                " VALUES (?, ?, ?, '.txt', 'document', 1, 1, 'x', ?, ?)",
                (path, path.rsplit("/", 1)[0], path.rsplit("/", 1)[1], time.time(), time.time()),
            )
        conn.commit()
    finally:
        conn.close()

    res = rag.forget_folder("/mnt/user/secret/")
    assert res["removed"]["files"] == 2
    conn = rag._get_conn(readonly=True)
    try:
        left = [
            r[0]
            for r in conn.execute(
                "SELECT canonical_path FROM indexed_files WHERE canonical_path LIKE '/mnt/user/secret%'"
            )
        ]
    finally:
        conn.close()
    assert left == ["/mnt/user/secretive/c.txt"]  # a sibling with the same prefix is kept
    assert "/mnt/user/secret" in rag.get_config()["excluded_paths"]


def test_forget_refuses_root():
    import pytest

    from backend.services.rag_engine import get_rag_engine

    with pytest.raises(ValueError):
        get_rag_engine().forget_folder("/")


def test_retention_deletes_old_unpinned_conversations(tmp_path):
    db = str(tmp_path / "c.db")
    convs.init_conversations_db(db)
    old = convs.create_conversation("u1", title="old", db_path=db)
    pinned = convs.create_conversation("u1", title="pinned", db_path=db)
    fresh = convs.create_conversation("u1", title="fresh", db_path=db)
    with convs.get_conv_db_connection(db) as conn:
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id IN (?, ?)",
            (time.time() - 40 * 86400, old["id"], pinned["id"]),
        )
        conn.execute("UPDATE conversations SET is_pinned = 1 WHERE id = ?", (pinned["id"],))
    assert convs.purge_conversations_older_than(0, db_path=db) == 0
    assert convs.purge_conversations_older_than(30, db_path=db) == 1
    with convs.get_conv_db_connection(db) as conn:
        ids = {r[0] for r in conn.execute("SELECT id FROM conversations")}
    assert ids == {pinned["id"], fresh["id"]}


def test_retention_setting_is_clamped():
    from backend.services.rag_engine import get_rag_engine

    rag = get_rag_engine()
    assert rag.update_config({"conversation_retention_days": "99999"})["conversation_retention_days"] == 3650
    assert rag.update_config({"conversation_retention_days": -5})["conversation_retention_days"] == 0
