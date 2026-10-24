"""Revert to the previous version (OPS-01/02/04 follow-up)."""

import sqlite3

import pytest

from backend import config
from backend.services import data_snapshot, self_updater


def _db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    conn.execute("DELETE FROM t")
    conn.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()


def _rows(path):
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT v FROM t")]


class FakeDocker:
    def __init__(self, health="healthy", image_present=True):
        self.calls = []
        self.health = health
        self.image_present = image_present

    def __call__(self, method, path, body=None, timeout=30.0):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/containers/zettnas-toolkit/json":
            return 200, {
                "Id": "cur123",
                "Image": "sha256:new",
                "Config": {"Env": [], "Image": "ghcr.io/x:latest"},
                "HostConfig": {},
                "Mounts": [{"Destination": "/app/data", "Source": "/host/data"}],
            }
        if method == "GET" and path.startswith("/images/"):
            if "sha256:old" in path and not self.image_present:
                return 404, {}
            return 200, {"Config": {"Labels": {"org.opencontainers.image.version": "1.9.3"}}}
        if method == "POST" and path.startswith("/containers/create"):
            return 201, {"Id": "new123456789"}
        if method == "GET" and path == "/containers/new123456789/json":
            return 200, {"State": {"Running": True, "Health": {"Status": self.health}}}
        return 204, {}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    # sleeping moves a fake clock, so the health dwell (OPS-6) passes instantly
    clock = {"t": 1000.0}
    monkeypatch.setattr(self_updater.time, "time", lambda: clock["t"])
    monkeypatch.setattr(self_updater.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))


def test_revert_restores_old_data_and_keeps_a_safety_snapshot(tmp_path, monkeypatch):
    _db(tmp_path / "users.db", ["v1.9.2 data"])
    old = data_snapshot.take_snapshot(
        str(tmp_path), "from-1.9.2", extra={"from_version": "1.9.2", "from_image": "sha256:old"}
    )
    _db(tmp_path / "users.db", ["v1.9.3 data"])
    fake = FakeDocker()
    monkeypatch.setattr(self_updater, "_docker_request", fake)

    self_updater.apply_update_from_helper(
        "zettnas-toolkit", "sha256:old", 0.0, data_dir=str(tmp_path), restore_from=old
    )

    assert _rows(tmp_path / "users.db") == ["v1.9.2 data"]
    create = next(b for m, p, b in fake.calls if p == "/containers/create?name=zettnas-toolkit")
    assert create["Image"] == "sha256:old"
    kinds = [s.get("kind") for s in data_snapshot.list_snapshots(str(tmp_path))]
    assert "revert" in kinds  # the 1.9.3 data was saved before restoring


def test_failed_revert_puts_the_current_data_back(tmp_path, monkeypatch):
    _db(tmp_path / "users.db", ["v1.9.2 data"])
    old = data_snapshot.take_snapshot(str(tmp_path), "from-1.9.2", extra={"from_image": "sha256:old"})
    _db(tmp_path / "users.db", ["v1.9.3 data"])
    monkeypatch.setattr(self_updater, "_docker_request", FakeDocker(health="unhealthy"))
    with pytest.raises(SystemExit):
        self_updater.apply_update_from_helper(
            "zettnas-toolkit", "sha256:old", 0.0, data_dir=str(tmp_path), restore_from=old
        )
    assert _rows(tmp_path / "users.db") == ["v1.9.3 data"]


def test_snapshot_being_restored_is_never_pruned(tmp_path):
    first = data_snapshot.take_snapshot(str(tmp_path), "a0")
    for i in range(data_snapshot.KEEP + 2):
        data_snapshot.take_snapshot(str(tmp_path), f"b{i}", protect=first)
    assert any(s["path"] == first for s in data_snapshot.list_snapshots(str(tmp_path)))


def test_revert_api_needs_password_and_a_present_image(client, auth_headers, token, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    data_snapshot.take_snapshot(
        str(tmp_path), "from-1.9.2", extra={"from_version": "1.9.2", "from_image": "sha256:old"}
    )
    fake = FakeDocker(image_present=False)
    monkeypatch.setattr("backend.services.container_mutator._docker_request", fake)
    spawned = []
    monkeypatch.setattr(self_updater, "spawn_self_updater", lambda *a, **k: spawned.append(a) or True)

    prev = client.get("/api/system/updates/previous", headers=auth_headers).json()["previous"]
    assert prev and prev[0]["version"] == "1.9.2" and prev[0]["image_available"] is False

    body = {"snapshot_id": prev[0]["id"], "current_password": "wrong"}
    assert client.post("/api/system/updates/revert", json=body, headers=auth_headers).status_code == 403
    body["current_password"] = "admin"
    assert client.post("/api/system/updates/revert", json=body, headers=auth_headers).status_code == 409
    fake.image_present = True
    res = client.post("/api/system/updates/revert", json=body, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert spawned and spawned[0][0] == "sha256:old" and spawned[0][3] == prev[0]["id"]
    bad = {"snapshot_id": "../../etc", "current_password": "admin"}
    assert client.post("/api/system/updates/revert", json=bad, headers=auth_headers).status_code == 404
