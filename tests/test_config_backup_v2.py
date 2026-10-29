"""App-config backup v2: what is exported, encryption, and safe restore."""

import io
import json
import sqlite3
import zipfile

import pytest

from backend.services import backup_engine


def _db(path, version=1, sessions=1):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS users (id TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (h TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS api_tokens (h TEXT)")
    conn.execute("INSERT INTO users VALUES ('u1')")
    for i in range(sessions):
        conn.execute("INSERT INTO sessions VALUES (?)", (f"s{i}",))
        conn.execute("INSERT INTO api_tokens VALUES (?)", (f"t{i}",))
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


@pytest.fixture
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(backend_engine_attr(), "DATA_DIR", str(d))
    _db(d / "users.db")
    (d / "security.json").write_text('{"x": 1}')
    (d / "secret.key").write_text("k" * 64)
    (d / "rag_index.db").write_text("huge index")
    (d / "auth_lockout.json").write_text("{}")
    (d / "vms.json").write_text('{"vm1": {}}')
    (d / "vms" / "vm1").mkdir(parents=True)
    (d / "vms" / "vm1" / "disk.qcow2").write_text("disk")
    (d / "vms" / "vm1" / "OVMF_VARS.fd").write_text("nvram")
    (d / "stacks" / "app").mkdir(parents=True)
    (d / "stacks" / "app" / "docker-compose.yml").write_text("services: {}")
    (d / "rclone" / "vfs_cache").mkdir(parents=True)
    (d / "rclone" / "rclone.conf").write_text("[remote]")
    (d / "rclone" / "vfs_cache" / "blob").write_text("cache")
    return d


def backend_engine_attr():
    return backup_engine


def _names(buf):
    with zipfile.ZipFile(buf) as z:
        return set(z.namelist())


def test_export_contents(data):
    names = _names(backup_engine.generate_backup_zip_stream())
    for wanted in (
        "users.db",
        "security.json",
        "vms.json",
        "vms/vm1/OVMF_VARS.fd",
        "stacks/app/docker-compose.yml",
        "rclone/rclone.conf",
        backup_engine.MANIFEST_NAME,
    ):
        assert wanted in names, wanted
    # the secret key only in an encrypted backup, never next to users.db in a plain zip (SEC-35)
    for unwanted in ("rag_index.db", "auth_lockout.json", "vms/vm1/disk.qcow2", "rclone/vfs_cache/blob", "secret.key"):
        assert unwanted not in names, unwanted


def test_an_encrypted_export_carries_the_secret_key(data):
    import io

    blob = backup_engine.generate_backup_zip_stream("a long backup passphrase").read()
    names = _names(io.BytesIO(backup_engine.decrypt_backup(blob, "a long backup passphrase")))
    assert "secret.key" in names and "users.db" in names


def test_exported_users_db_has_no_sessions_or_tokens(data, tmp_path):
    buf = backend_engine_attr().generate_backup_zip_stream()
    with zipfile.ZipFile(buf) as z:
        (tmp_path / "out.db").write_bytes(z.read("users.db"))
        manifest = json.loads(z.read(backup_engine.MANIFEST_NAME))
    conn = sqlite3.connect(tmp_path / "out.db")
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
    conn.close()
    assert manifest["format"] == 2 and "users.db" in manifest["files"]


def test_encrypted_round_trip_and_wrong_passphrase(data):
    blob = backup_engine.generate_backup_zip_stream(passphrase="correct horse").read()
    assert blob.startswith(backup_engine.ENCRYPTED_MAGIC) and b"security.json" not in blob
    with pytest.raises(ValueError, match="Wrong passphrase"):
        backup_engine.restore_backup_archive(io.BytesIO(blob), passphrase="nope nope")
    with pytest.raises(ValueError, match="encrypted"):
        backup_engine.restore_backup_archive(io.BytesIO(blob))
    (data / "security.json").write_text('{"x": 2}')
    res = backup_engine.restore_backup_archive(io.BytesIO(blob), passphrase="correct horse")
    assert (data / "security.json").read_text() == '{"x": 1}'
    assert res["snapshot"] and res["restored"] >= 5


def test_restore_drops_sessions_and_refuses_newer_schema(data, tmp_path):
    # An old-style export that still carries sessions
    _db(tmp_path / "old_users.db", sessions=3)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(tmp_path / "old_users.db", "users.db")
    buf.seek(0)
    backup_engine.restore_backup_archive(buf, snapshot=False)
    conn = sqlite3.connect(data / "users.db")
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM api_tokens").fetchone()[0] == 0
    conn.close()

    _db(tmp_path / "newer.db", version=99)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.write(tmp_path / "newer.db", "users.db")
    buf.seek(0)
    with pytest.raises(ValueError, match="newer ZettNAS"):
        backup_engine.restore_backup_archive(buf, snapshot=False)


def test_restore_ignores_files_an_export_never_contains(data):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("rag_index.db", "evil")
        z.writestr("vms/vm1/disk.qcow2", "overwrite a disk")
        z.writestr("led_state.json", "{}")
    buf.seek(0)
    backup_engine.restore_backup_archive(buf, snapshot=False)
    assert (data / "rag_index.db").read_text() == "huge index"
    assert (data / "vms" / "vm1" / "disk.qcow2").read_text() == "disk"
    assert (data / "led_state.json").exists()
