"""B10 / REL-4, REL-10: storage features say when they can't work; the UPS never cuts power blind."""

import pytest

from backend.services import snapshot_service, ups_watchdog


class _NoSnapshots:
    def get_capabilities(self):
        from backend.hardware.pal.base import PlatformCapabilities, PlatformType

        return PlatformCapabilities(platform=PlatformType.GENERIC_LINUX, is_observer_mode=False, can_snapshot=False)


def test_no_snapshot_schedule_is_offered_where_snapshots_cannot_run(client, auth_headers, monkeypatch):
    monkeypatch.setattr(snapshot_service, "_pal", lambda: _NoSnapshots())
    body = client.get("/api/snapshots/schedules", headers=auth_headers).json()
    assert body["available"] is False and "missing" in body["reason"]
    res = client.put(
        "/api/snapshots/schedules", json={"share": "photos", "every": "daily", "keep": 7}, headers=auth_headers
    )
    assert res.status_code == 400 and "missing" in res.json()["detail"]


class _Run:
    def __init__(self, code):
        self.returncode, self.stdout, self.stderr = code, "", "nope"


@pytest.fixture
def failsafe(monkeypatch):
    calls = {"cut": 0, "events": [], "notified": []}
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)
    monkeypatch.setattr(ups_watchdog, "load_ups_config", lambda: {"poweroff_ups": True})
    monkeypatch.setattr(ups_watchdog, "graceful_docker_teardown", lambda timeout_sec=30: None)
    monkeypatch.setattr(ups_watchdog, "log_ups_event", lambda **kw: None)
    monkeypatch.setattr(ups_watchdog, "add_event", lambda *a, **k: calls["events"].append(a[1]))
    monkeypatch.setattr(ups_watchdog, "send_ups_cut_power", lambda: calls.__setitem__("cut", calls["cut"] + 1))
    monkeypatch.setattr(ups_watchdog.os, "sync", lambda: None)
    monkeypatch.setattr(ups_watchdog, "_failsafe_engaged", False)
    import backend.services.notifications as n

    monkeypatch.setattr(n, "send_notification", lambda **kw: calls["notified"].append(kw["title"]))
    return calls


def test_without_a_host_shutdown_path_the_ups_outlets_are_not_cut(failsafe, monkeypatch):
    monkeypatch.setattr(ups_watchdog, "host_shutdown_paths", lambda: [])
    ups_watchdog.execute_atomic_failsafe_shutdown(5, 2, "battery low")
    assert failsafe["cut"] == 0
    assert "UPS: shut the NAS down by hand" in failsafe["events"] and failsafe["notified"]


def test_a_failing_shutdown_command_is_not_reported_as_success(failsafe, monkeypatch):
    import subprocess

    monkeypatch.setattr(ups_watchdog, "host_shutdown_paths", lambda: ["/host/powerdown"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Run(1))
    ups_watchdog.execute_atomic_failsafe_shutdown(5, 2, "battery low")
    assert failsafe["cut"] == 0


def test_the_ups_is_told_to_cut_power_only_after_the_host_shutdown_started(failsafe, monkeypatch):
    import subprocess

    monkeypatch.setattr(ups_watchdog, "host_shutdown_paths", lambda: ["/host/powerdown"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Run(0))
    ups_watchdog.execute_atomic_failsafe_shutdown(5, 2, "battery low")
    assert failsafe["cut"] == 1


def test_poweroff_inside_a_container_does_not_count_as_a_host_shutdown(monkeypatch):
    monkeypatch.setattr(ups_watchdog.os.path, "exists", lambda p: p in ("/.dockerenv", "/sbin/poweroff"))
    monkeypatch.setattr(ups_watchdog.os, "access", lambda p, m: True)
    assert ups_watchdog.host_shutdown_paths() == []
