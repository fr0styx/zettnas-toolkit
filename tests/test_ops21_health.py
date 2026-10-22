"""OPS-21: /api/health returns 503 when the app is degraded, so Docker and the updater notice."""

import time

from fastapi.testclient import TestClient

from backend.api import system
from backend.main import app
from backend.state import Z_STATE


def test_healthy(monkeypatch):
    monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time())
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.json()["checks"] == {"collector": "ok", "database": "ok", "data_dir": "ok"}


def test_stale_collector_is_503(monkeypatch):
    monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time() - 3600)
    r = TestClient(app).get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["collector"] == "failed"


def test_starting_is_200_then_failed_after_grace(monkeypatch):
    monkeypatch.setattr(Z_STATE, "collector_heartbeat", 0.0)
    monkeypatch.setattr(system, "_PROCESS_STARTED", time.time())
    r = TestClient(app).get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "starting"
    monkeypatch.setattr(system, "_PROCESS_STARTED", time.time() - 3600)
    assert TestClient(app).get("/api/health").status_code == 503


def test_database_failure_is_503(monkeypatch):
    import backend.users_db as udb

    def broken(*a, **k):
        raise OSError("disk gone")

    monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time())
    monkeypatch.setattr(udb, "users_db_session", broken)
    r = TestClient(app).get("/api/health")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "failed"
