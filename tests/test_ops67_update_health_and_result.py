"""Updates: the new version must report "ok" for 60 s (OPS-6); every outcome is recorded and a
rollback is reported once, as an event and a notification (OPS-7)."""

import json

import pytest

from backend.services import self_updater as su


class Clock:
    def __init__(self):
        self.t = 1000.0

    def time(self):
        return self.t

    def sleep(self, s):
        self.t += s


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(su.time, "time", c.time)
    monkeypatch.setattr(su.time, "sleep", c.sleep)
    monkeypatch.setattr(
        su, "_docker_request", lambda *a, **k: (200, {"State": {"Running": True, "Health": {"Status": "healthy"}}})
    )
    return c


def test_starting_does_not_count_and_ok_must_hold(clock, monkeypatch):
    seen = iter(["starting"] * 10 + ["ok"] * 100)
    monkeypatch.setattr(su, "_app_status", lambda cid: next(seen))
    t0 = clock.t
    ok, why = su._wait_until_healthy("c1")
    assert ok and why.startswith("ok for")
    assert clock.t - t0 >= 10 * 3 + su.APP_OK_DWELL_SECS  # waited out "starting", then the dwell


def test_a_relapse_during_the_dwell_restarts_it(clock, monkeypatch):
    seen = iter(["ok"] * 5 + ["starting"] + ["ok"] * 100)
    monkeypatch.setattr(su, "_app_status", lambda cid: next(seen))
    t0 = clock.t
    assert su._wait_until_healthy("c1")[0]
    assert clock.t - t0 >= 6 * 3 + su.APP_OK_DWELL_SECS


def test_degraded_fails_at_once(clock, monkeypatch):
    monkeypatch.setattr(su, "_app_status", lambda cid: "degraded")
    assert su._wait_until_healthy("c1") == (False, "the app reported a failed part (degraded)")


def test_rollback_is_recorded_and_reported_once(tmp_path, monkeypatch):
    events, notes = [], []
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda *a, **k: notes.append(a))
    su.write_update_result(str(tmp_path), "rolled_back", "timed out waiting for the app to report ok", to_image="img:2")
    stored = json.loads((tmp_path / su.RESULT_FILE).read_text())
    assert stored["result"] == "rolled_back" and stored["reported"] is False
    assert su.report_last_update_result(str(tmp_path))["result"] == "rolled_back"
    assert events and events[0][0] == "error" and notes and "img:2" in notes[0][1]
    assert su.report_last_update_result(str(tmp_path)) is None  # once only
    assert len(notes) == 1


def test_last_result_endpoint(client, auth_headers, tmp_path, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    assert client.get("/api/system/updates/last-result", headers=auth_headers).json() == {"result": None}
    su.write_update_result(str(tmp_path), "updated", "ok for 60 s", to_image="img:3")
    body = client.get("/api/system/updates/last-result", headers=auth_headers).json()
    assert body["result"] == "updated" and body["to_image"] == "img:3"
