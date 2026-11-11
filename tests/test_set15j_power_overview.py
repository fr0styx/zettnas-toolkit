"""SET-15 (Power 2): the Overview says when the UPS cannot be read, stopped answering, or nothing can switch the NAS off."""

from unittest.mock import patch

from backend.services import status_summary as ss


def _kinds(ups, silent=False, path_ok=True):
    ss._PATH_CACHE.update(at=-1e9, ok=True)
    with (
        patch("backend.hardware.ups.read_ups_status", return_value=ups),
        patch("backend.services.ups_watchdog.ups_went_silent", return_value=silent),
        patch("backend.services.ups_watchdog.shutdown_path_report", return_value={"ok": path_ok}),
    ):
        return [i["kind"] for i in ss._power()]


def test_unreadable():
    assert "ups_unreadable" in _kinds({"available": False, "unreadable": True})


def test_silent_during_a_cut():
    assert "ups_silent" in _kinds({"available": False}, silent=True)


def test_nothing_switches_off_only_with_a_ups():
    assert "power_nobody" in _kinds({"available": True, "status": "OL"}, path_ok=False)
    assert "power_nobody" not in _kinds({"available": False}, path_ok=False)


def test_a_healthy_ups_adds_nothing():
    assert _kinds({"available": True, "status": "OL"}) == []
