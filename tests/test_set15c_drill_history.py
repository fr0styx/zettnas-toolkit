"""SET-15 (Power B4): the practice run leaves no "power restored" row; a real cut still does."""

from unittest.mock import patch

from backend.services import ups_watchdog as wd


def _run(states, drill_flags):
    logged = []
    wd._outage_start_ts = None
    wd._outage_is_drill = False
    with (
        patch.object(wd, "log_ups_event", side_effect=lambda **k: logged.append(k["event_type"])),
        patch.object(wd, "add_event"),
        patch.object(wd, "execute_atomic_failsafe_shutdown"),
        patch.object(wd, "shutdown_path_report", return_value={"ok": True, "detail": ""}),
    ):
        for i, (status, drill) in enumerate(zip(states, drill_flags, strict=True)):
            with patch.object(wd, "is_simulation_active", return_value=drill):
                wd.check_ups_power_watchdog(
                    {"available": True, "status": status, "battery_charge_pct": 99, "time_left_min": 40},
                    1000.0 + i * 10,
                )
    return logged


def test_a_drill_writes_no_recovery():
    assert "OUTAGE_RECOVERED" not in _run(["OL", "OL", "OL"], [True, True, False])


def test_a_real_cut_still_does():
    assert "OUTAGE_RECOVERED" in _run(["OB", "OB", "OL"], [False, False, False])
