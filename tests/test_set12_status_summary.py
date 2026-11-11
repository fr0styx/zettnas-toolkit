"""SET-12: the Overview is fine only when every check ran; an alert's button leads to a place that
has to do with it."""

from backend.services import status_summary


def test_a_check_that_fails_is_named_and_the_answer_is_not_ok(monkeypatch):
    def broken():
        raise RuntimeError("no reading")

    broken.__name__ = "_drives"
    monkeypatch.setattr(status_summary, "CHECKS", (broken, lambda: []))
    got = status_summary.summary()
    assert got == {"ok": False, "items": [], "unchecked": ["drives"]}  # it said ok: True, having looked at nothing


def test_every_check_ran_and_found_nothing_is_ok(monkeypatch):
    monkeypatch.setattr(status_summary, "CHECKS", (lambda: [], lambda: None))
    assert status_summary.summary() == {"ok": True, "items": [], "unchecked": []}


def test_too_hot_opens_hardware_and_a_stalled_service_the_event_log(monkeypatch):
    from backend.state import Z_STATE

    monkeypatch.setattr(Z_STATE, "critical_temp_active", True, raising=False)
    from backend.hardware import ups

    monkeypatch.setattr(ups, "read_ups_status", lambda: {"available": False, "status": ""})
    hot = [i for i in status_summary._power() if i["kind"] == "too_hot"]
    assert hot and hot[0]["open"] == "hardware"
    assert "hardware" in status_summary.ACT_SCOPES and "events" in status_summary.ACT_SCOPES


def test_every_place_an_alert_can_open_is_a_link_the_page_knows():
    import os
    import re

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "frontend", "src", "router.js"), encoding="utf-8") as fh:
        router = fh.read()
    routes = set(re.findall(r"^  '?([a-z/]+)'?: \(", router, flags=re.M))
    with open(os.path.join(root, "backend", "services", "status_summary.py"), encoding="utf-8") as fh:
        src = fh.read()
    places = (
        set(re.findall(r'"open": "([a-z]+)"', src))
        | set(re.findall(r'"open": "([a-z]+)" if', src))
        | {"backup", "storage", "drives"}
    )
    assert places <= routes, f"no link for: {sorted(places - routes)}"
    assert {"hardware", "appearance", "overview", "events", "activity"} <= routes
