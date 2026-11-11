"""SET-08: one reader of the UPS status, one shutdown rule where the first limit reached wins, and
a shutdown sequence in which no single step can cancel the rest. A simulated UPS is stepped
through a power cut; no plug is pulled."""

import pytest

from backend.hardware import ups, ups_state
from backend.services import ups_watchdog as wd

CFG = {
    "shutdown_policy": "runtime_left",
    "runtime_threshold_min": 5,
    "battery_threshold_pct": 20,
    "shutdown_timer_sec": 300,
}


@pytest.mark.parametrize(
    "status, state, low",
    [
        ("OL", "online", False),
        ("OL CHRG", "online", False),
        ("ONLINE", "online", False),
        ("OL CHRG LB", "online", True),  # back on mains after a long cut: charging, battery still low
        ("OB", "on_battery", False),
        ("OB DISCHRG", "on_battery", False),
        ("OB LB", "on_battery", True),
        ("ONBATT", "on_battery", False),
        ("ON BATTERY", "on_battery", False),
        ("ONBATT LOWBATT", "on_battery", True),
        ("LB", "on_battery", True),  # says nothing about mains: not proven to be on it
        ("OL NOBATT", "online", False),  # "OB" was looked for inside "NOBATT"
        ("NOBATT", "unknown", False),
        ("COMMLOST", "unknown", False),
        ("PERMISSION_REQUIRED", "unknown", False),
        ("", "unknown", False),
        (None, "unknown", False),
    ],
)
def test_one_reading_of_the_status(status, state, low):
    assert ups_state.power_state(status) == state
    assert ups_state.battery_low(status) is low


@pytest.mark.parametrize(
    "policy, status, charge, runtime, elapsed, fires",
    [
        # on mains nothing fires, whatever the battery says
        ("runtime_left", "OL", 5, 1, 9999, False),
        ("runtime_left", "OL CHRG LB", 5, 1, 9999, False),
        ("timer", "OL", 100, 60, 9999, False),
        # the UPS's own signal
        ("runtime_left", "OB LB", 80, 30, 6, True),
        # the first limit reached wins, whichever rule was once chosen
        ("runtime_left", "OB", 80, 5, 6, True),
        ("runtime_left", "OB", 80, 5.1, 6, False),
        ("runtime_left", "OB", 20, 30, 6, True),
        ("battery_pct", "OB", 80, 4, 6, True),
        ("battery_pct", "OB", 21, 30, 6, False),
        ("timer", "OB", 15, 30, 6, True),
        # one figure missing: the other still counts
        ("runtime_left", "OB", 19, None, 6, True),
        ("runtime_left", "OB", None, 4, 6, True),
        ("runtime_left", "OB", 50, None, 9999, False),
        # "after a set time" only where it was chosen ...
        ("timer", "OB", 90, 60, 299, False),
        ("timer", "OB", 90, 60, 300, True),
        ("runtime_left", "OB", 90, 60, 9999, False),
        # ... and always for a UPS that reports neither figure: the rule can not fail to fire
        ("runtime_left", "OB", None, None, 299, False),
        ("runtime_left", "OB", None, None, 300, True),
        ("battery_pct", "ONBATT", None, None, 301, True),
    ],
)
def test_the_first_limit_reached_wins(policy, status, charge, runtime, elapsed, fires):
    reason = ups_state.shutdown_reason(status, charge, runtime, elapsed, {**CFG, "shutdown_policy": policy})
    assert bool(reason) is fires, reason


@pytest.fixture
def nas(monkeypatch):
    """A NAS that switches itself off, with a simulated UPS: every outside effect is recorded."""
    seen = {"steps": [], "events": [], "pushes": [], "restarted": 0, "host_off": 0}
    for name, value in (
        ("_outage_start_ts", None),
        ("_outage_start_charge", None),
        ("_outage_start_volts", None),
        ("_failsafe_engaged", False),
        ("_host_shutdown_started", False),
        ("_silent_alerted", False),
        ("_simulation_active", False),
        ("_copy_paused_by_failsafe", False),
    ):
        monkeypatch.setattr(wd, name, value)
    monkeypatch.setattr(wd, "load_ups_config", lambda: dict(CFG))
    monkeypatch.setattr(wd, "log_ups_event", lambda **kw: seen["events"].append(kw["event_type"] + ":" + kw["status"]))
    monkeypatch.setattr(wd, "add_event", lambda level, title, *a, **k: seen["events"].append(title))
    monkeypatch.setattr(wd, "nut_forced_shutdown", lambda: seen["steps"].append("pcs"))
    monkeypatch.setattr(wd, "_machines_first", lambda: seen["steps"].append("machines"))
    monkeypatch.setattr(wd, "graceful_docker_teardown", lambda timeout: seen["steps"].append("apps") or {})
    monkeypatch.setattr(wd.os, "sync", lambda: seen["steps"].append("sync"))
    monkeypatch.setattr(wd, "shutdown_owner", lambda: "kiboto")
    monkeypatch.setattr(wd, "signal_host_powerdown", lambda: seen.__setitem__("host_off", seen["host_off"] + 1) or True)
    monkeypatch.setattr(wd, "restart_stopped_apps", lambda: seen.__setitem__("restarted", seen["restarted"] + 1) or [])
    from backend.services import notifications

    monkeypatch.setattr(notifications, "send_notification", lambda **kw: seen["pushes"].append(kw["text"]["title_key"]))
    return seen


def reading(status, charge=100.0, runtime=40.0):
    return {
        "available": True,
        "status": status,
        "battery_charge_pct": charge,
        "time_left_min": runtime,
        "line_volts": 230,
    }


def test_a_power_cut_step_by_step(nas):
    wd.check_ups_power_watchdog(reading("OL"), 0)
    wd.check_ups_power_watchdog(reading("OB DISCHRG", 95, 30), 10)  # the cut begins
    wd.check_ups_power_watchdog(reading("OB DISCHRG", 60, 12), 300)
    assert nas["host_off"] == 0 and nas["steps"] == []
    wd.check_ups_power_watchdog(reading("OB DISCHRG", 30, 5), 600)  # five minutes left: the first limit
    assert nas["steps"] == ["pcs", "machines", "apps", "sync"]
    assert nas["host_off"] == 1
    assert nas["pushes"] == ["alert.ups_shutdown_now.title"]
    wd.check_ups_power_watchdog(reading("OB LB", 10, 1), 660)  # further readings start nothing twice
    assert nas["host_off"] == 1


def test_mains_returning_during_the_shutdown_starts_nothing_again(nas):
    wd.check_ups_power_watchdog(reading("OB", 30, 4), 0)
    wd.check_ups_power_watchdog(reading("OB", 30, 4), 6)
    assert nas["host_off"] == 1
    wd.check_ups_power_watchdog(reading("OL CHRG", 31, 5), 20)  # the NAS is going down
    assert nas["restarted"] == 0  # apps were started into the shutdown, and their list deleted
    assert wd._failsafe_engaged is True


def test_a_low_battery_on_mains_starts_no_shutdown(nas):
    """After a long cut the UPS says "on mains, charging, battery low". That flag alone started the
    sequence again five seconds after every start, until the battery had recharged."""
    for t in (0, 6, 60, 600):
        wd.check_ups_power_watchdog(reading("OL CHRG LB", 8, 2), t)
    assert nas["host_off"] == 0 and nas["steps"] == [] and nas["pushes"] == []
    for t in (700, 706):
        wd.check_ups_power_watchdog(reading("OL NOBATT", None, None), t)  # battery unplugged: not "on battery"
    assert nas["host_off"] == 0


def test_a_short_flicker_starts_nothing_and_apps_come_back_after_a_handed_over_cut(nas, monkeypatch):
    wd.check_ups_power_watchdog(reading("OB LB", 5, 1), 0)
    wd.check_ups_power_watchdog(reading("OB LB", 5, 1), 4)  # under five seconds
    assert nas["host_off"] == 0
    monkeypatch.setattr(wd, "shutdown_owner", lambda: "unraid")  # the host's own UPS service shuts down
    wd.check_ups_power_watchdog(reading("OB LB", 5, 1), 6)
    assert nas["steps"] == ["pcs", "machines", "apps", "sync"] and nas["host_off"] == 0
    wd.check_ups_power_watchdog(reading("OL CHRG", 6, 2), 60)  # mains came back before the host went down
    assert nas["restarted"] == 1 and wd._failsafe_engaged is False


def test_a_failing_step_does_not_cancel_the_shutdown(nas, monkeypatch, caplog):
    def broken(*a, **k):
        raise RuntimeError("no docker")

    monkeypatch.setattr(wd, "nut_forced_shutdown", broken)
    monkeypatch.setattr(wd, "graceful_docker_teardown", broken)
    monkeypatch.setattr(wd, "_machines_first", broken)
    from backend.services import notifications

    monkeypatch.setattr(notifications, "send_notification", broken)
    with caplog.at_level("ERROR"):
        wd.execute_atomic_failsafe_shutdown(15, 3, "test")
    assert nas["steps"] == ["sync"] and nas["host_off"] == 1
    assert sum("failed, going on" in r.message for r in caplog.records) == 4  # said as errors, not at debug level


def test_the_time_rule_also_says_that_the_shutdown_starts(nas, monkeypatch):
    monkeypatch.setattr(wd, "load_ups_config", lambda: {**CFG, "shutdown_policy": "timer", "shutdown_timer_sec": 60})
    wd.check_ups_power_watchdog(reading("OB", 90, 50), 0)
    wd.check_ups_power_watchdog(reading("OB", 90, 50), 61)
    assert nas["host_off"] == 1 and nas["pushes"] == ["alert.ups_shutdown_now.title"]


def test_a_ups_that_falls_silent_during_a_cut_is_said_once(nas):
    silent = {"available": False, "unreadable": True}
    wd.check_ups_power_watchdog(silent, 0)  # no cut: nothing to say
    assert nas["pushes"] == []
    wd.check_ups_power_watchdog(reading("OB", 80, 30), 10)
    wd.check_ups_power_watchdog(silent, 40)
    wd.check_ups_power_watchdog(silent, 50)
    assert nas["pushes"] == ["alert.ups_silent.title"]
    assert wd._outage_start_ts == 10  # the cut is not taken for over
    wd.check_ups_power_watchdog(reading("OB", 70, 25), 60)  # it answers again, still on battery
    wd.check_ups_power_watchdog(silent, 90)
    assert nas["pushes"] == ["alert.ups_silent.title"] * 2
    assert nas["restarted"] == 0 and nas["host_off"] == 0


def test_an_error_reply_is_no_ups_never_online(monkeypatch):
    assert not ups_state.is_reading({})
    assert not ups_state.is_reading({"UPSNAME": "ups"})  # all that an error reply left behind
    assert ups_state.is_reading({"STATUS": "OL"})
    assert ups_state.is_reading({"PERMISSION_ERROR": True})

    monkeypatch.setattr(
        ups, "load_ups_config", lambda: {"enabled": True, "mode": "nut_client", "host": "10.0.0.9", "port": 3493}
    )
    monkeypatch.setattr(ups, "_query_nut_socket", lambda *a, **k: {"UPSNAME": "ups", "MODEL": "Back-UPS"})
    monkeypatch.setattr(ups, "_query_nut_cli", lambda *a, **k: {})
    monkeypatch.setattr(ups, "_ups_set_up", lambda: True)
    monkeypatch.setattr(ups, "_CACHED_UPS", {})
    got = ups.read_ups_status(force=True)
    assert got["available"] is False and got["unreadable"] is True and got["status"] == "Not readable"

    monkeypatch.setattr(ups, "_query_nut_socket", lambda *a, **k: {"STATUS": "OL CHRG LB", "BCHARGE": "12"})
    got = ups.read_ups_status(force=True)
    assert (
        got["available"]
        and got["power_state"] == "online"
        and got["battery_low"] is True
        and got["on_battery"] is False
    )

    test = ups.test_ups_connection(mode="nut_client", host="10.0.0.9", port=3493)
    assert test["success"] is True
    monkeypatch.setattr(ups, "_query_nut_socket", lambda *a, **k: {"UPSNAME": "ups"})
    test = ups.test_ups_connection(mode="nut_client", host="10.0.0.9", port=3493)
    assert test["success"] is False and "no status" in test["error"]


def test_overview_reports_a_power_cut_on_every_connection_type(monkeypatch):
    from backend.services import status_summary

    for status, cut in (
        ("OB DISCHRG", True),
        ("ONBATT", True),
        ("ON BATTERY", True),
        ("ONLINE", False),
        ("OL NOBATT", False),
    ):
        monkeypatch.setattr(ups, "read_ups_status", lambda status=status: {"available": True, "status": status})
        kinds = [item["kind"] for item in status_summary._power()]
        assert ("on_battery" in kinds) is cut, status
