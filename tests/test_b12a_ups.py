"""B12a (REL-10, D10): one UPS engine; on Unraid and TrueNAS the host's own UPS service shuts the
server down; only ZettNAS's apps are stopped, in parallel, within the timeout; the drill says
what will shut the server down, or that nothing will."""

import time

import pytest

from backend.services import ups_watchdog as uw
from backend.state import Z_STATE


def _containers():
    return [
        {"id": "a1", "name": "immich", "state": "running", "zettnas_app": True},
        {"id": "b1", "name": "jellyfin", "state": "running", "stack": "jellyfin"},
        {"id": "c1", "name": "someone-elses", "state": "running", "stack": "their-project"},
        {"id": "d1", "name": "zettnas-ollama", "state": "running", "zettnas_app": True},
        {"id": "e1", "name": "paperless", "state": "exited", "zettnas_app": True},
    ]


def test_only_zettnas_apps_are_stopped(monkeypatch):
    monkeypatch.setattr(uw, "_catalog_ids", lambda: {"jellyfin", "immich"})
    assert [c["name"] for c in uw.zettnas_containers(_containers())] == ["immich", "jellyfin"]


def test_they_stop_in_parallel_and_the_wait_is_bounded(monkeypatch):
    import backend.hardware.docker_stats as ds

    monkeypatch.setattr(uw, "_catalog_ids", lambda: {"jellyfin"})
    monkeypatch.setattr(ds, "read_docker_containers", _containers)

    def stop(cid, action):
        time.sleep(3 if cid == "b1" else 0.2)
        return {"success": True}

    monkeypatch.setattr(ds, "container_action", stop)
    started = time.monotonic()
    res = uw.graceful_docker_teardown(timeout_sec=1)
    assert time.monotonic() - started < 2.5  # not 3.2 s one after the other
    assert res["stopped"] == ["immich"] and res["timed_out"] == ["jellyfin"]


@pytest.fixture
def failsafe(monkeypatch):
    calls = {"powerdown": 0, "cut": 0, "events": []}
    monkeypatch.setattr(uw, "load_ups_config", lambda: {"poweroff_ups": True})
    monkeypatch.setattr(uw, "graceful_docker_teardown", lambda timeout_sec=30: {"stopped": []})
    monkeypatch.setattr(uw, "log_ups_event", lambda **kw: None)
    monkeypatch.setattr(uw, "add_event", lambda *a, **k: calls["events"].append(a[1]))
    monkeypatch.setattr(
        uw, "signal_host_powerdown", lambda: calls.__setitem__("powerdown", calls["powerdown"] + 1) or True
    )
    monkeypatch.setattr(uw, "send_ups_cut_power", lambda: calls.__setitem__("cut", calls["cut"] + 1))
    monkeypatch.setattr(uw.os, "sync", lambda: None)
    monkeypatch.setattr(uw, "_failsafe_engaged", False)
    return calls


@pytest.mark.parametrize("host", ["unraid", "truenas"])
def test_on_unraid_and_truenas_the_host_shuts_down(failsafe, monkeypatch, host):
    monkeypatch.setattr(uw, "shutdown_owner", lambda: host)
    uw.execute_atomic_failsafe_shutdown(5, 2, "battery low")
    assert failsafe["powerdown"] == 0 and failsafe["cut"] == 0  # never powered off, never cut
    assert "UPS: handed to the host" in failsafe["events"]


def test_elsewhere_zettnas_shuts_down_and_only_then_cuts(failsafe, monkeypatch):
    monkeypatch.setattr(uw, "shutdown_owner", lambda: "zettnas")
    uw.execute_atomic_failsafe_shutdown(5, 2, "battery low")
    assert failsafe["powerdown"] == 1 and failsafe["cut"] == 1


def test_the_drill_reports_the_host_s_ups_service(monkeypatch):
    monkeypatch.setattr(uw, "shutdown_owner", lambda: "unraid")
    monkeypatch.setattr(uw, "host_ups_service", lambda: {"kind": "apcupsd", "battery_pct": "10", "minutes": "10"})
    rep = uw.shutdown_path_report()
    assert rep["ok"] is True and "10% battery or 10 minutes" in rep["detail"] and "Unraid" in rep["detail"]
    monkeypatch.setattr(uw, "host_ups_service", lambda: None)
    rep = uw.shutdown_path_report()
    assert rep["ok"] is False and "nothing shuts the server down" in rep["detail"]


def test_the_drill_reports_zettnas_s_own_shutdown_command(monkeypatch):
    monkeypatch.setattr(uw, "shutdown_owner", lambda: "zettnas")
    monkeypatch.setattr(uw, "host_shutdown_paths", lambda: ["/host/powerdown"])
    assert uw.shutdown_path_report() == {
        "by": "zettnas",
        "ok": True,
        "detail": "ZettNAS shuts the server down with /host/powerdown.",
    }
    monkeypatch.setattr(uw, "host_shutdown_paths", lambda: [])
    assert uw.shutdown_path_report()["ok"] is False


def test_the_host_s_apcupsd_is_found_through_the_gateway(monkeypatch):
    import backend.hardware.ups as ups

    monkeypatch.setattr(uw, "_gateway", lambda: "172.30.0.1")
    seen = []

    def query(host, port, timeout):
        seen.append(host)
        return {"STATUS": "ONLINE", "MBATTCHG": "15 Percent", "MINTIMEL": "7 Minutes"} if host == "172.30.0.1" else {}

    monkeypatch.setattr(ups, "_query_apcupsd_socket", query)
    assert uw.host_ups_service() == {"kind": "apcupsd", "battery_pct": "15", "minutes": "7"}
    assert seen[0] == "172.30.0.1"


def test_a_drill_returns_the_shutdown_path(monkeypatch):
    monkeypatch.setattr(uw, "shutdown_path_report", lambda: {"by": "unraid", "ok": True, "detail": "x"})
    monkeypatch.setattr(uw, "log_ups_event", lambda **kw: None)
    res = uw.trigger_outage_simulation(5)
    uw.end_simulation_drill()
    assert res["shutdown_path"]["ok"] is True


def test_a_copy_paused_by_the_failsafe_carries_on_when_power_returns(failsafe, monkeypatch):
    monkeypatch.setattr(uw, "shutdown_owner", lambda: "unraid")
    Z_STATE.copy_active, Z_STATE.copy_paused = True, False
    try:
        uw.execute_atomic_failsafe_shutdown(5, 2, "battery low")
        assert Z_STATE.copy_paused is True
        assert uw.resume_copy_after_outage() is True and Z_STATE.copy_paused is False
        assert uw.resume_copy_after_outage() is False  # only once
    finally:
        Z_STATE.copy_active = False
        Z_STATE.copy_paused = False


def test_the_shutdown_owner_follows_the_platform(monkeypatch):
    from types import SimpleNamespace

    from backend.hardware.pal.base import PlatformType

    for platform, owner in (
        (PlatformType.UNRAID, "unraid"),
        (PlatformType.TRUENAS, "truenas"),
        (PlatformType.GENERIC_LINUX, "zettnas"),
    ):
        adapter = SimpleNamespace(get_platform_type=lambda p=platform: p)
        monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda a=adapter: a)
        assert uw.shutdown_owner() == owner


def test_the_gateway_is_read_from_the_routing_table(tmp_path):
    route = tmp_path / "route"
    route.write_text(
        "Iface\tDestination\tGateway \tFlags\neth0\t0015A8C0\t00000000\t0001\neth0\t00000000\t0100A8C0\t0003\n"
    )
    assert uw._gateway(str(route)) == "192.168.0.1"
    assert uw._gateway(str(tmp_path / "missing")) is None


def test_the_teardown_survives_a_broken_docker(monkeypatch):
    import backend.hardware.docker_stats as ds

    monkeypatch.setattr(ds, "read_docker_containers", lambda: 1 / 0)
    assert uw.graceful_docker_teardown(1) == {"stopped": [], "failed": [], "timed_out": []}
    monkeypatch.setattr(ds, "read_docker_containers", lambda: [])
    assert uw.graceful_docker_teardown(1)["stopped"] == []


def test_a_container_that_fails_to_stop_is_reported(monkeypatch):
    import backend.hardware.docker_stats as ds

    monkeypatch.setattr(uw, "_catalog_ids", lambda: set())
    monkeypatch.setattr(
        ds, "read_docker_containers", lambda: [{"id": "x", "name": "app", "state": "running", "zettnas_app": True}]
    )
    monkeypatch.setattr(ds, "container_action", lambda cid, action: 1 / 0)
    assert uw.graceful_docker_teardown(1)["failed"] == ["app"]
    monkeypatch.setattr(ds, "container_action", lambda cid, action: {"success": False})
    assert uw.graceful_docker_teardown(1)["failed"] == ["app"]


def test_an_unknown_platform_or_catalog_falls_back_safely(monkeypatch):
    def broken():
        raise RuntimeError("no platform")

    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", broken)
    assert uw.shutdown_owner() == "zettnas"
    monkeypatch.setattr("backend.services.app_catalog.get_all_catalog_apps", broken)
    assert uw._catalog_ids() == set()


def test_nut_on_the_host_counts_as_its_ups_service(monkeypatch):
    import backend.hardware.ups as ups

    monkeypatch.setattr(uw, "_gateway", lambda: "10.9.0.1")
    monkeypatch.setattr(ups, "_query_apcupsd_socket", lambda host, port, timeout: {})
    monkeypatch.setattr(uw, "_nut_answers", lambda host, timeout=1.5: host == "10.9.0.1")
    assert uw.host_ups_service() == {"kind": "nut", "battery_pct": "", "minutes": ""}
    monkeypatch.setattr(uw, "_nut_answers", lambda host, timeout=1.5: False)
    assert uw.host_ups_service() is None
