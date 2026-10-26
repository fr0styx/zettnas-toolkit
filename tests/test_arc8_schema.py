"""ARC-8: schema changes live in db_schema.py; added columns appear on old databases."""

import glob
import os
import sqlite3

from backend import db_schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_no_alter_table_outside_db_schema():
    stray = []
    for f in glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True):
        if f.endswith("db_schema.py"):
            continue
        with open(f, encoding="utf-8") as fh:
            if "ALTER TABLE" in fh.read().upper():
                stray.append(os.path.relpath(f, ROOT))
    assert not stray, "put the change in backend/db_schema.py (COLUMN_UPGRADES or MIGRATIONS): " + ", ".join(stray)


def test_ensure_columns_adds_what_an_old_table_lacks_once():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE users (user_id TEXT PRIMARY KEY, username TEXT)")
    added = db_schema.ensure_columns(conn, "users.db")
    assert added == [f"users.{c}" for _, c, _ in db_schema.COLUMN_UPGRADES["users.db"]]
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    assert {"mfa_enabled", "idp_type", "idp_sub"} <= cols
    assert db_schema.ensure_columns(conn, "users.db") == []  # a second start adds nothing


def test_a_missing_table_is_left_to_the_init_code():
    conn = sqlite3.connect(":memory:")
    assert db_schema.ensure_columns(conn, "rag_index.db") == []
    assert db_schema.ensure_columns(conn, "unknown.db") == []


def test_added_columns_keep_the_schema_version():
    # additive columns need no version bump, so an older image still opens the database
    assert all(v == 1 for v, _ in db_schema.SCHEMA_VERSIONS.values())
