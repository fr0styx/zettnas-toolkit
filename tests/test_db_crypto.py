"""Encryption at rest for the AI index and chat history (AI-20)."""

import io
import os
import sqlite3 as std_sqlite3
import threading
import zipfile

import pytest

from backend import db_crypto

KEY = "correct horse battery staple 42"


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv(db_crypto.KEY_ENV, KEY)


def _plain_conversations(path):
    from backend.services import ai_conversations_db as conv

    conv.init_conversations_db(str(path))
    with conv.get_conv_db_connection(str(path)) as c:
        c.execute(
            "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES ('c1', 'u1', 'Secret plans for Tuesday', 1, 1)"
        )
        c.execute("PRAGMA user_version = 1")
    return conv


def test_existing_chats_are_converted_and_only_open_with_the_key(tmp_path, monkeypatch):
    path = tmp_path / "ai_conversations.db"
    conv = _plain_conversations(path)
    assert db_crypto.is_plaintext(str(path))

    monkeypatch.setenv(db_crypto.KEY_ENV, KEY)
    assert db_crypto.prepare(str(path)) == "converted"
    assert db_crypto.is_encrypted(str(path)) and not os.path.exists(str(path) + "-wal")
    assert b"Secret plans" not in path.read_bytes()
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    with conv.get_conv_db_connection(str(path)) as c:
        assert c.execute("SELECT title FROM conversations").fetchone()[0] == "Secret plans for Tuesday"
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    with pytest.raises(std_sqlite3.DatabaseError):
        std_sqlite3.connect(str(path)).execute("SELECT * FROM conversations").fetchall()
    assert db_crypto.prepare(str(path)) == "encrypted"  # idempotent


def test_missing_or_wrong_key_leaves_the_file_closed_and_untouched(tmp_path, monkeypatch):
    path = tmp_path / "ai_conversations.db"
    conv = _plain_conversations(path)
    monkeypatch.setenv(db_crypto.KEY_ENV, KEY)
    db_crypto.prepare(str(path))
    before = path.read_bytes()

    monkeypatch.delenv(db_crypto.KEY_ENV)
    with pytest.raises(db_crypto.DataKeyError, match="not set"):
        db_crypto.prepare(str(path))
    with pytest.raises(db_crypto.sqlite3.DatabaseError):
        conv.init_conversations_db(str(path))

    monkeypatch.setenv(db_crypto.KEY_ENV, "a different key entirely")
    with pytest.raises(db_crypto.DataKeyError, match="wrong key"):
        db_crypto.prepare(str(path))
    assert path.read_bytes() == before

    monkeypatch.setenv(db_crypto.KEY_ENV, "short")
    with pytest.raises(db_crypto.DataKeyError, match="at least"):
        db_crypto.prepare(str(path))


def test_without_a_key_nothing_changes(tmp_path):
    path = tmp_path / "ai_conversations.db"
    _plain_conversations(path)
    assert db_crypto.prepare(str(path)) == "plain"
    assert db_crypto.is_plaintext(str(path))


def test_new_index_is_created_encrypted_and_vector_search_works(tmp_path, keyed):
    import struct

    from backend.services.rag_engine import RagSearchEngine

    eng = RagSearchEngine(db_path=str(tmp_path / "rag_index.db"))
    eng._ensure_schema()
    assert db_crypto.is_encrypted(eng.db_path)
    conn = eng._get_conn()
    try:
        if eng._has_sqlite_vec:
            vec = struct.pack("<4f", 1, 0, 0, 0)
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS vec_t USING vec0(id INTEGER PRIMARY KEY, e FLOAT[4])")
            conn.execute("INSERT INTO vec_t VALUES (1, ?)", (vec,))
            conn.commit()
            assert conn.execute("SELECT id FROM vec_t WHERE e MATCH ? AND k = 1", (vec,)).fetchall()[0][0] == 1
    finally:
        conn.close()
    eng.close()


def test_snapshot_and_backup_copies_stay_encrypted(tmp_path, monkeypatch):
    from backend.services import backup_engine, data_snapshot

    path = tmp_path / "ai_conversations.db"
    _plain_conversations(path)
    monkeypatch.setenv(db_crypto.KEY_ENV, KEY)
    db_crypto.prepare(str(path))

    copy = tmp_path / "snap" / "ai_conversations.db"
    copy.parent.mkdir()
    data_snapshot._copy_db(str(path), str(copy))
    assert db_crypto.is_encrypted(str(copy))

    blob = backup_engine._snapshot_db_bytes(str(path))
    assert blob[:16] != db_crypto.SQLITE_HEADER and b"Secret plans" not in blob
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("ai_conversations.db", blob)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z:
        backup_engine._check_archive_schema(z, {"ai_conversations.db"})  # opens with the key
        monkeypatch.delenv(db_crypto.KEY_ENV)
        with pytest.raises(ValueError, match="encrypted"):
            backup_engine._check_archive_schema(z, {"ai_conversations.db"})


def test_index_waits_while_it_is_being_encrypted(tmp_path, monkeypatch):
    path = str(tmp_path / "rag_index.db")
    gate = threading.Event()
    real_prepare = db_crypto.prepare
    monkeypatch.setattr(db_crypto, "prepare", lambda p: (gate.wait(5), real_prepare(p))[1])
    db_crypto.prepare_in_background(path)
    with pytest.raises(db_crypto.sqlite3.OperationalError, match="being encrypted"):
        db_crypto.wait_ready(path)
    assert db_crypto.status(path) == "encrypting"
    gate.set()
    db_crypto.wait_ready(path, timeout=5)
    db_crypto._ready.pop(path, None)
