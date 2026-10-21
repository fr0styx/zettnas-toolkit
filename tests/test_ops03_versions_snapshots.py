"""OPS-03: schema versions, refusing newer databases, pre-update snapshots."""

import os
import sqlite3

import pytest

from backend import config, db_schema
from backend.services import data_snapshot, self_updater


def _db(path, version, rows=("a",)):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("DELETE FROM t")
    conn.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    conn.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()


def _rows(path):
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT v FROM t")]
    finally:
        conn.close()


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "USERS_DB_PATH", str(tmp_path / "users.db"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "history.db"))
    return tmp_path


def test_stamp_then_refuse_a_newer_database(data):
    _db(data / "users.db", 0)
    _db(data / "history.db", 0)
    db_schema.stamp_versions()
    assert db_schema.read_version(str(data / "users.db")) == db_schema.SCHEMA_VERSIONS["users.db"][0]
    db_schema.check_versions()  # same version: fine

    _db(data / "users.db", 99)
    with pytest.raises(db_schema.NewerDatabaseError, match="users.db"):
        db_schema.check_versions()


def test_newer_search_index_is_moved_aside(data):
    _db(data / "rag_index.db", 99)
    moved = db_schema.check_versions()
    assert len(moved) == 1 and not (data / "rag_index.db").exists() and os.path.exists(moved[0])


def test_snapshot_round_trip_skips_index_and_keeps_three(data):
    _db(data / "users.db", 1, rows=("before",))
    _db(data / "rag_index.db", 1)
    (data / "security.json").write_text('{"v": 1}')
    (data / "rclone").mkdir()
    (data / "rclone" / "rclone.conf").write_text("[remote]")

    snap = data_snapshot.take_snapshot(str(data), label="from-1.9.1")
    assert not os.path.exists(os.path.join(snap, "rag_index.db"))

    _db(data / "users.db", 2, rows=("after",))
    (data / "security.json").write_text('{"v": 2}')
    (data / "rclone" / "rclone.conf").write_text("[changed]")
    data_snapshot.restore_snapshot(snap, str(data))
    assert _rows(data / "users.db") == ["before"]
    assert db_schema.read_version(str(data / "users.db")) == 1
    assert (data / "security.json").read_text() == '{"v": 1}'
    assert (data / "rclone" / "rclone.conf").read_text() == "[remote]"

    for i in range(4):
        data_snapshot.take_snapshot(str(data), label=f"n{i}")
        os.utime(data, None)
    assert len(data_snapshot.list_snapshots(str(data))) <= data_snapshot.KEEP


class FakeDocker:
    """Minimal Docker API for the updater, with a configurable health result."""

    def __init__(self, health="healthy", data_source="/mnt/user/appdata/z/data"):
        self.calls = []
        self.health = health
        self.data_source = data_source

    def __call__(self, method, path, body=None, timeout=30.0):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/containers/zettnas-toolkit/json":
            return 200, {
                "Id": "old123",
                "Image": "sha256:old",
                "Config": {"Env": []},
                "HostConfig": {},
                "Mounts": [{"Destination": "/app/data", "Source": self.data_source}],
            }
        if method == "GET" and path.startswith("/images/"):
            return 200, {"Config": {"Labels": {"org.opencontainers.image.version": "1.9.1"}}}
        if method == "POST" and path.startswith("/containers/create"):
            return 201, {"Id": "new123456789"}
        if method == "GET" and path == "/containers/new123456789/json":
            return 200, {"State": {"Running": True, "Health": {"Status": self.health}}}
        return 204, {}


def test_spawn_mounts_the_data_folder_into_the_helper(monkeypatch):
    fake = FakeDocker()
    monkeypatch.setattr(self_updater, "_docker_request", fake)
    assert self_updater.spawn_self_updater("img:new", "zettnas-toolkit", 0.1)
    create = next(b for m, p, b in fake.calls if p.startswith("/containers/create?name=zettnas-self-updater"))
    assert "/mnt/user/appdata/z/data:/zettnas-data" in create["HostConfig"]["Binds"]
    assert create["Cmd"][-2:] == ["--data-dir", "/zettnas-data"]


def test_unhealthy_update_restores_the_snapshot(monkeypatch, data):
    _db(data / "users.db", 1, rows=("before",))
    monkeypatch.setattr(self_updater.time, "sleep", lambda s: None)

    fake = FakeDocker(health="unhealthy")

    def docker(method, path, body=None, timeout=30.0):
        if method == "POST" and path == "/containers/new123456789/start":
            # The new version migrates the database as it starts.
            _db(data / "users.db", 2, rows=("migrated",))
        return fake(method, path, body, timeout)

    monkeypatch.setattr(self_updater, "_docker_request", docker)
    with pytest.raises(SystemExit):
        self_updater.apply_update_from_helper("zettnas-toolkit", "img:new", delay=0.0, data_dir=str(data))
    assert _rows(data / "users.db") == ["before"]
    snaps = data_snapshot.list_snapshots(str(data))
    assert snaps and snaps[0]["from_version"] == "1.9.1"
