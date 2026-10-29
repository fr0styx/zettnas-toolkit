"""ARC-30: every database opens through backend.sqlite_conn.connect with its profile, and a
migration that fails stops startup instead of leaving ZettNAS on a half-updated layout."""

import pathlib
import sqlite3

import pytest

from backend import db_schema
from backend.sqlite_conn import PROFILES, connect

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["users", "history"])
def test_profiles_are_applied(tmp_path, name):
    conn = connect(name, str(tmp_path / f"{name}.db"))
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 15000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == (1 if "foreign_keys=ON" in PROFILES[name]["pragmas"] else 0)
    finally:
        conn.close()


def test_the_ai_databases_use_wal(tmp_path):
    conn = connect("ai_conversations", str(tmp_path / "conv.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        conn.execute("CREATE TABLE t (a)")
        conn.execute("INSERT INTO t VALUES (1)")
        assert conn.execute("SELECT a FROM t").fetchone()["a"] == 1  # rows by name, any driver
    finally:
        conn.close()


@pytest.mark.parametrize(
    "rel",
    [
        "backend/users_db.py",
        "backend/db.py",
        "backend/services/ai_conversations_db.py",
        "backend/services/rag_engine.py",
    ],
)
def test_the_helpers_open_through_connect(rel):
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "from backend.sqlite_conn import connect" in src
    for pragma in ("PRAGMA busy_timeout", "PRAGMA synchronous"):
        assert pragma not in src, f"{rel} sets {pragma} itself"


def test_a_failed_migration_stops_startup(tmp_path, monkeypatch):
    for name in db_schema.SCHEMA_VERSIONS:
        p = pathlib.Path(db_schema._path(name, str(tmp_path)))
        p.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(p).close()

    def broken(name, path):
        raise db_schema.sqlite3.OperationalError("disk I/O error")  # the driver db_schema uses

    monkeypatch.setattr(db_schema, "migrate", broken)
    with pytest.raises(RuntimeError, match="could not be updated"):
        db_schema.stamp_versions(str(tmp_path))


def test_a_missing_ai_key_only_warns(tmp_path, monkeypatch, caplog):
    for name in db_schema.SCHEMA_VERSIONS:
        p = pathlib.Path(db_schema._path(name, str(tmp_path)))
        p.parent.mkdir(parents=True, exist_ok=True)
        sqlite3.connect(p).close()

    def locked(name, path):
        raise db_schema.DataKeyError("no key")

    monkeypatch.setattr(db_schema, "migrate", locked)
    db_schema.stamp_versions(str(tmp_path))
    assert "Could not open" in caplog.text
