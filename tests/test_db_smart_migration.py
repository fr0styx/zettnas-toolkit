"""An older history database gains the SMART power-on-hours column once, quietly (ARC-4)."""

import sqlite3

from backend import db
from backend import ignored_errors as ie


def _cols(path):
    with sqlite3.connect(path) as conn:
        return {row[1] for row in conn.execute("PRAGMA table_info(smart_history)")}


def test_an_old_smart_table_gains_the_column_and_nothing_is_ignored(tmp_path, monkeypatch):
    path = str(tmp_path / "history.db")
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE smart_history (ts INTEGER, dev TEXT, temp REAL, PRIMARY KEY (ts, dev))")
    monkeypatch.setattr(db, "DB_PATH", path)
    ie.reset()
    db.init_db()
    assert "power_on_hours" in _cols(path)
    db.init_db()  # a second start: no duplicate-column error to ignore
    assert "backend.db.init_db" not in [s["where"] for s in ie.snapshot()["top"]]
