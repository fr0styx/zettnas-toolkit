"""B15 (PERF-19): with no UPS set up and none found, detection backs off (1, 5, 15 min) instead of a
full probe every 10 s; a set-up UPS keeps its pace; USB changes, the Power pane and a saved config
look again."""

import pytest

from backend.hardware import ups


@pytest.fixture
def probes(monkeypatch, tmp_path):
    calls = []
    for name in (
        "_query_direct_usb",
        "_query_apcupsd_socket",
        "_query_nut_socket",
        "_query_apcaccess_cli",
        "_query_nut_cli",
    ):
        monkeypatch.setattr(ups, name, lambda *a, _n=name, **k: calls.append(_n) or {})
    monkeypatch.setattr(ups, "_get_docker_gateway", lambda: None)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(ups.time, "time", lambda: clock["t"])
    usb = {"devices": ["1-1", "usb1"]}
    monkeypatch.setattr(ups, "_usb_devices", lambda: tuple(usb["devices"]))
    monkeypatch.setattr(ups, "UPS_CONFIG_FILE", str(tmp_path / "ups_config.json"))
    monkeypatch.setattr(ups, "load_ups_config", lambda: dict(ups.DEFAULT_UPS_CONFIG))
    ups._CACHED_UPS = {}
    ups._LAST_UPS_POLL = 0.0
    ups._forget_nothing_found()
    yield calls, clock, usb, tmp_path
    ups._CACHED_UPS = {}
    ups._LAST_UPS_POLL = 0.0
    ups._forget_nothing_found()


def _probe_rounds(calls):
    return calls.count("_query_apcupsd_socket")  # the default mode probes apcupsd first


def test_nothing_set_up_and_nothing_found_backs_off(probes):
    calls, clock, _usb, _tmp = probes
    assert ups.read_ups_status()["protocol"] == "offline"
    assert _probe_rounds(calls) == 1
    for secs, rounds in (
        (30, 1),
        (61, 2),
        (61 + 200, 2),
        (61 + 301, 3),
        (61 + 301 + 600, 3),
        (61 + 301 + 901, 4),
        (61 + 301 + 901 + 901, 5),
    ):
        clock["t"] = 1_000_000.0 + secs
        ups.read_ups_status()
        assert _probe_rounds(calls) == rounds, secs


def test_a_set_up_ups_keeps_polling_every_ten_seconds(probes):
    calls, clock, _usb, tmp = probes
    (tmp / "ups_config.json").write_text('{"mode": "apcupsd_client", "host": "10.0.0.5"}')
    ups.read_ups_status()
    clock["t"] += 11
    ups.read_ups_status()
    assert calls.count("_query_apcupsd_socket") == 2


def test_a_usb_change_the_power_pane_and_force_look_again(probes):
    calls, clock, usb, _tmp = probes
    ups.read_ups_status()
    clock["t"] += 11
    ups.read_ups_status()
    assert _probe_rounds(calls) == 1  # backing off
    ups.read_ups_status(reprobe=True)
    assert _probe_rounds(calls) == 2  # the Power pane is open
    clock["t"] += 11
    usb["devices"].append("1-2")
    ups.read_ups_status()
    assert _probe_rounds(calls) == 3  # something was plugged in
    ups.read_ups_status(force=True)
    assert _probe_rounds(calls) == 4


def test_a_ups_found_resets_the_back_off(probes, monkeypatch):
    calls, clock, _usb, _tmp = probes
    ups.read_ups_status()
    assert ups._NOTHING_FOUND["step"] == 1
    monkeypatch.setattr(
        ups, "_query_apcupsd_socket", lambda *a, **k: {"STATUS": "ONLINE", "BCHARGE": "90.0", "MODEL": "Back-UPS"}
    )
    ups.read_ups_status(force=True)
    assert ups._NOTHING_FOUND == {"until": 0.0, "step": 0, "usb": None}


def test_config_recovery_runs_once_per_back_off(monkeypatch, tmp_path):
    lookups = []
    monkeypatch.setattr(ups, "UPS_CONFIG_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(ups, "POOL_PATH", str(tmp_path / "pool"))
    monkeypatch.setattr(ups, "_detect_host_nut_config", lambda *a: lookups.append("nut") or None)
    monkeypatch.setattr("backend.db.get_app_config_value", lambda key: lookups.append("db") or None)
    ups._forget_nothing_found()
    try:
        a = ups.load_ups_config()
        b = ups.load_ups_config()
        assert a == b and lookups == ["db", "nut"]  # the second load came from memory
        a["mode"] = "changed"
        assert ups.load_ups_config()["mode"] != "changed"  # a copy, not the memo itself
        ups._forget_nothing_found()  # what saving a config does
        ups.load_ups_config()
        assert lookups == ["db", "nut", "db", "nut"]
    finally:
        ups._forget_nothing_found()


def test_usb_devices_reads_sysfs_names(monkeypatch, tmp_path):
    (tmp_path / "1-1").mkdir()
    (tmp_path / "usb1").mkdir()
    monkeypatch.setattr(ups, "USB_DEVICE_ROOTS", [str(tmp_path), str(tmp_path / "missing")])
    assert ups._usb_devices() == ("1-1", "usb1")
