"""NREL-9: a database that can't be opened is left alone; only a damaged one is replaced."""

import sqlite3

from backend.services import data_health


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE t (x)")
    conn.commit()
    conn.close()


def test_states(tmp_path, monkeypatch):
    good = tmp_path / "good.db"
    _db(good)
    assert data_health._db_state(str(good)) == "ok"
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not sqlite at all" * 100)
    assert data_health._db_state(str(junk)) == "damaged"

    from backend import db_crypto

    def denied(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(db_crypto, "connect", denied)
    assert data_health._db_state(str(good)) == "unreadable"


def test_an_unreadable_database_is_not_replaced(tmp_path, monkeypatch):
    users = tmp_path / "users.db"
    _db(users)
    monkeypatch.setattr(data_health, "_db_state", lambda p: "unreadable")
    monkeypatch.setattr(data_health, "_record_event", lambda result: None)
    out = data_health.check_and_repair(str(tmp_path))
    assert out["unreadable"] == ["users.db"] and out["lost"] == [] and out["repaired"] == {}
    assert users.exists() and not list(tmp_path.glob("*.corrupt-*"))
