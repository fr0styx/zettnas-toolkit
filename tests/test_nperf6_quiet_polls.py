"""NPERF-6: the pool alert state is written only when it changes; with no app running, Docker
is asked once a minute, or as soon as someone opens Apps."""

import inspect

from backend.hardware import docker_stats
from backend.services import pool_alerts


def test_the_state_is_written_only_when_it_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(pool_alerts, "_state_file", lambda: str(tmp_path / "pool_alerts.json"))
    writes = []
    real = pool_alerts.atomic_write_json
    monkeypatch.setattr(pool_alerts, "atomic_write_json", lambda p, d: writes.append(p) or real(p, d))
    item = {"id": "pool:cache", "level": "warning", "kind": "pool_degraded", "subject": "cache"}
    found = [item]
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: list(found))
    monkeypatch.setitem(pool_alerts._cache, "ok", True)
    sent = []
    pool_alerts.check_and_alert(1000.0, send=lambda **k: sent.append(k["dedup_key"]))
    assert sent == ["pool:cache"] and len(writes) == 1
    pool_alerts.check_and_alert(1300.0, send=lambda **k: sent.append(k["dedup_key"]))
    assert len(writes) == 1  # nothing new: no write
    found.clear()
    pool_alerts.check_and_alert(1600.0, send=lambda **k: sent.append(k["dedup_key"]))
    assert sent[-1] == "pool:cache:fixed" and len(writes) == 2


def test_docker_waits_a_minute_or_for_someone_with_no_apps(monkeypatch):
    waits = []
    monkeypatch.setattr(docker_stats._DEMAND_WAKE, "wait", lambda secs: waits.append(secs) or True)
    docker_stats._DEMAND_WAKE.set()
    docker_stats._wait_for_apps()
    assert waits == [docker_stats.NO_APPS_SECS] and docker_stats.NO_APPS_SECS >= 60
    assert not docker_stats._DEMAND_WAKE.is_set()  # cleared for the next round
    assert "_wait_for_apps()" in inspect.getsource(docker_stats._docker_telemetry_worker)
