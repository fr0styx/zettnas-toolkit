"""B10 / ARC-17, ARC-19, ARC-20: startup never changes or loses data before its safety steps have run."""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_importing_the_app_opens_no_database(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    env = {**os.environ, "DATA_DIR": str(data), "PYTHONPATH": ROOT, "USERS_DB_PATH": str(data / "users.db")}
    r = subprocess.run(
        [sys.executable, "-c", "import backend.main, backend.auth, backend.services.ai_conversations_db"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr[-2000:]
    assert not [n for n in os.listdir(data) if n.endswith(".db")], os.listdir(data)


def test_health_reads_a_real_table(client, tmp_path, monkeypatch):
    import contextlib
    import sqlite3

    from backend import users_db
    from backend.api import system

    assert system._health_checks()["database"] == "ok"
    empty = sqlite3.connect(tmp_path / "users.db")  # a users.db with no tables, as after a failed repair

    @contextlib.contextmanager
    def no_tables(db_path=None):
        yield empty

    monkeypatch.setattr(users_db, "users_db_session", no_tables)
    assert system._health_checks()["database"] == "failed"


def test_a_wrong_data_key_locks_the_chat_history_instead_of_moving_it(tmp_path, monkeypatch):
    from backend import db_crypto
    from backend.services import data_health

    path = tmp_path / "ai_conversations.db"
    path.write_bytes(b"x" * 64)
    monkeypatch.setattr(db_crypto, "applies_to", lambda p: True)
    monkeypatch.setattr(db_crypto, "is_encrypted", lambda p: True)
    monkeypatch.setattr(db_crypto, "enabled", lambda: True)

    def wrong_key(p):
        raise db_crypto.DataKeyError("ai_conversations.db is encrypted and the key does not open it")

    monkeypatch.setattr(db_crypto, "_verify", wrong_key)
    result = data_health.check_and_repair(str(tmp_path))
    assert result["lost"] == [] and result["repaired"] == {}
    assert path.exists() and not list(tmp_path.glob("*.corrupt-*"))  # nothing moved aside


def test_an_unreadable_secret_key_is_never_replaced(tmp_path, monkeypatch):
    from backend import config

    key_dir = tmp_path / "secret.key"
    key_dir.mkdir()  # reading it fails like a permissions slip would
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(key_dir))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="was not replaced"):
        config._get_or_create_secret_key()
    assert key_dir.is_dir()


def test_a_missing_or_empty_secret_key_is_created_once(tmp_path, monkeypatch):
    from backend import config

    keyfile = tmp_path / "secret.key"
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(keyfile))
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    first = config._get_or_create_secret_key()
    assert keyfile.read_text() == first and oct(keyfile.stat().st_mode)[-3:] == "600"
    assert config._get_or_create_secret_key() == first  # read back, not replaced
    keyfile.write_text("")
    second = config._get_or_create_secret_key()
    assert second and second != first and keyfile.read_text() == second
