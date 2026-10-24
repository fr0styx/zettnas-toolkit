"""Numbered schema migrations, upgrades from v1 fixture databases, lock-free reads (ARCH-7)."""

import os
import sqlite3
import threading

import pytest

from backend import config, db, db_schema

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "schema_v1")


def _load_fixture(name, path):
    with open(os.path.join(FIXTURES, name.replace(".db", ".sql")), encoding="utf-8") as f:
        sql = f.read()
    conn = sqlite3.connect(path)
    conn.executescript(sql)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def test_users_db_from_v1_keeps_its_accounts(tmp_path, monkeypatch):
    from backend.users_db import get_user_by_username, init_users_db

    path = str(tmp_path / "users.db")
    _load_fixture("users.db", path)
    monkeypatch.setattr(config, "USERS_DB_PATH", path)
    init_users_db(path)
    assert db_schema.migrate("users.db", path) == db_schema.SCHEMA_VERSIONS["users.db"][0]
    user = get_user_by_username("fixtureuser", db_path=path)
    assert user and user["role_id"] == "share_user"


def test_history_db_from_v1_keeps_its_rows(tmp_path, monkeypatch):
    path = str(tmp_path / "history.db")
    _load_fixture("history.db", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.close_history_connection()
    db.init_db()
    assert db_schema.migrate("history.db", path) == db_schema.SCHEMA_VERSIONS["history.db"][0]
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0] == 1
        assert conn.execute("SELECT reallocated_sectors FROM smart_history WHERE dev = 'sda'").fetchone()[0] == 2
    finally:
        conn.close()


def test_migrations_run_in_order_once_each(tmp_path, monkeypatch):
    path = str(tmp_path / "x.db")
    sqlite3.connect(path).close()
    ran = []
    steps = [
        lambda c: (ran.append(2), c.execute("CREATE TABLE t (a INTEGER)")),
        lambda c: (ran.append(3), c.execute("ALTER TABLE t ADD COLUMN b TEXT")),
    ]
    monkeypatch.setitem(db_schema.MIGRATIONS, "x.db", steps)
    assert db_schema.migrate("x.db", path) == 3
    assert db_schema.migrate("x.db", path) == 3
    assert ran == [2, 3]


def test_a_failing_migration_changes_nothing(tmp_path, monkeypatch):
    path = str(tmp_path / "y.db")
    sqlite3.connect(path).close()

    def bad(c):
        c.execute("CREATE TABLE half (a INTEGER)")
        raise RuntimeError("boom")

    monkeypatch.setitem(db_schema.MIGRATIONS, "y.db", [bad])
    with pytest.raises(RuntimeError):
        db_schema.migrate("y.db", path)
    conn = sqlite3.connect(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone()
    finally:
        conn.close()


def test_history_reads_do_not_wait_for_the_write_lock():
    db.init_db()
    done = threading.Event()

    def read():
        db.query_history("24h")
        done.set()

    with db._DB_LOCK:  # a writer holds the lock
        t = threading.Thread(target=read)
        t.start()
        assert done.wait(5), "history read waited for the write lock"
    t.join()
