"""B10 / REL-6, REL-7: alerts that arrive, and that don't cry wolf."""

import pytest

from backend.services import drive_alerts


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(drive_alerts, "_send", lambda **kw: out.append(kw))
    drive_alerts._hot.clear()
    return out


KEY = "serial:ZXA1"  # the same disk, whatever its kernel name


def _v(verdict, summary="Commands to the drive keep timing out"):
    return {"verdict": verdict, "label": verdict, "summary": summary}


def test_a_stable_drive_alerts_once_then_stays_quiet(sent):
    t = 1_000_000.0
    assert drive_alerts.on_verdict("sdb", _v("ok"), key=KEY, now=t) == "first"
    assert drive_alerts.on_verdict("sdb", _v("watch"), key=KEY, now=t + 60) == "alert"
    for i in range(2, 200):  # every check for days afterwards
        assert drive_alerts.on_verdict("sdb", _v("watch"), key=KEY, now=t + 60 * i) == ""
    assert len(sent) == 1 and sent[0]["level"] == "warning"


def test_replace_now_reminds_daily_and_better_news_is_not_pushed(sent):
    t = 2_000_000.0
    drive_alerts.on_verdict("sdb", _v("now"), key=KEY, now=t)
    assert drive_alerts.on_verdict("sdb", _v("now"), key=KEY, now=t + 3600) == ""
    assert drive_alerts.on_verdict("sdb", _v("now"), key=KEY, now=t + 25 * 3600) == "reminder"
    assert drive_alerts.on_verdict("sdb", _v("soon"), key=KEY, now=t + 26 * 3600) == "better"
    assert [s["level"] for s in sent] == ["critical", "critical"]


def test_a_renamed_disk_keeps_its_own_history(sent):
    t = 3_000_000.0
    drive_alerts.on_verdict("sdb", _v("watch"), key=KEY, now=t)
    # after a reboot the same disk (same serial) is sdc: no new alert
    assert drive_alerts.on_verdict("sdc", _v("watch"), key=KEY, now=t + 600) == ""


def test_temperature_alerts_once_per_crossing_with_hysteresis(sent):
    seen = []
    send = lambda **kw: seen.append(kw)  # noqa: E731
    temps = [49, 50, 51, 50, 49, 50, 51, 48, 46, 50]
    for temp in temps:
        drive_alerts.check_temperatures([{"dev": "sda", "temp": temp}], 50, send)
    # crossed at 50, stayed around it, re-armed only after 46 (= 50 - 3), crossed again at 50
    assert len(seen) == 2 and all(s["event_type"] == "temp" for s in seen)
    drive_alerts.check_temperatures([{"dev": "sda", "temp": 61}], 50, send)
    assert seen[-1]["level"] == "critical"
    drive_alerts.check_temperatures([{"dev": "sda", "temp": 30, "standby": True}], 50, send)
    assert len(seen) == 3


def test_the_wizard_address_is_saved_even_from_an_old_client(client, auth_headers):
    res = client.post(
        "/api/notifications/config",
        json={"urls": ["https://ntfy.sh/zettnas-test-topic"], "enabled": True},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    cfg = client.get("/api/notifications/config", headers=auth_headers).json()
    assert cfg["enabled"] is True and len(cfg["apprise_urls"]) == 1


def test_personal_routes_run_while_shared_channels_are_off(monkeypatch):
    from backend.services import notifications

    routed = []
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"enabled": False, "push_enabled": False})
    monkeypatch.setattr(notifications, "_route_to_people", lambda cfg, *a: routed.append(a))
    res = notifications.send_notification(title="Disk", message="m", level="critical", event_type="smart")
    assert routed and res.get("reason") == "disabled"


def test_the_lasting_name_is_the_serial(monkeypatch):
    from backend.hardware import disks

    monkeypatch.setattr(disks, "_discover_disks", lambda: [{"dev": "sdb", "serial": "ZXA1", "wwn": ""}])
    assert disks.drive_identity("sdb") == "serial:ZXA1"
    assert disks.drive_identity("sdq") == "dev:sdq"
