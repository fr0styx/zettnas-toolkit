"""The opt-in anonymous health report: off by default, weekly, nothing personal."""

import json

import pytest

from backend.services import health_signal as hs


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(hs, "_next_check", 0.0)
    monkeypatch.delenv("HEALTH_SIGNAL_URL", raising=False)


def test_it_is_off_and_unavailable_by_default():
    st = hs.status()
    assert st["enabled"] is False and st["available"] is False
    assert hs.maybe_send() is False


def test_the_report_holds_only_the_listed_fields(monkeypatch):
    from backend.state import Z_STATE

    monkeypatch.setattr(
        Z_STATE,
        "cached_stats",
        {
            "name": "my-secret-nas",
            "ip": "192.0.2.10",
            "disks": [{"dev": f"sd{c}", "serial": "WD-123"} for c in "abcde"],
            "hardware": {"has_lcd": True, "has_mcu": False},
            "docker": [{"name": "plex", "state": "running"}],
            "ups": {"available": True},
        },
    )
    r = hs.report("a" * 32)
    assert set(r) == {"schema", "id", "version", "platform", "arch", "variant", "drives", "features"}
    assert r["drives"] == "5-8" and r["features"] == ["containers", "lcd", "ups"]
    text = json.dumps(r)
    for private in ("my-secret-nas", "192.0.2.10", "WD-123", "plex", "sda"):
        assert private not in text


@pytest.mark.parametrize("n, bucket", [(0, "0"), (1, "1-2"), (3, "3-4"), (8, "5-8"), (16, "9-16"), (40, "17+")])
def test_drive_ranges(n, bucket):
    assert hs.drive_bucket(n) == bucket


def test_turning_it_on_makes_an_id_and_off_forgets_it():
    on = hs.set_enabled(True)
    assert on["enabled"] and len(on["install_id"]) == 32
    again = hs.set_enabled(True)
    assert again["install_id"] == on["install_id"]
    off = hs.set_enabled(False)
    assert off == {"enabled": False, "install_id": "", "last_sent": 0.0}
    assert hs.set_enabled(True)["install_id"] != on["install_id"]  # a new opt-in is not linkable


def test_sends_weekly_only_when_enabled_and_retries_later(monkeypatch):
    monkeypatch.setenv("HEALTH_SIGNAL_URL", "https://receiver.example/v1/report")
    T = 1_790_000_000.0  # a real clock: the first report is due at once
    sent = []
    monkeypatch.setattr(hs, "send", lambda state: sent.append(state["install_id"]) or True)
    assert hs.maybe_send(now=T, mono=0.0) is False  # not enabled
    hs.set_enabled(True)
    monkeypatch.setattr(hs, "_next_check", 0.0)
    assert hs.maybe_send(now=T, mono=10.0) is True
    assert hs.maybe_send(now=T + 1000, mono=20.0) is False  # within the hour: the file isn't even read
    assert hs.maybe_send(now=T + 1000, mono=20.0 + hs.CHECK_EVERY_SECS) is False  # within the week
    assert hs.maybe_send(now=T + hs.SEND_EVERY_SECS, mono=30.0 + 2 * hs.CHECK_EVERY_SECS) is True
    assert len(sent) == 2

    def offline(state):
        raise OSError("no route")

    monkeypatch.setattr(hs, "send", offline)
    mono = 40.0 + 3 * hs.CHECK_EVERY_SECS
    assert hs.maybe_send(now=T + 3 * hs.SEND_EVERY_SECS, mono=mono) is False
    assert hs._next_check == mono + hs.RETRY_AFTER_FAILURE_SECS


def test_send_posts_the_report(monkeypatch):
    monkeypatch.setenv("HEALTH_SIGNAL_URL", "https://receiver.example/v1/report")
    seen = {}

    class Resp:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), method=req.get_method(), timeout=timeout)
        return Resp()

    monkeypatch.setattr(hs.urllib.request, "urlopen", fake_urlopen)
    assert hs.send({"install_id": "b" * 32}) is True
    assert seen["url"] == "https://receiver.example/v1/report" and seen["method"] == "POST"
    assert seen["body"]["id"] == "b" * 32 and seen["timeout"] == hs.TIMEOUT_SECS


def test_the_api(client, auth_headers, monkeypatch):
    r = client.put("/api/system/health-signal", headers=auth_headers, json={"enabled": True})
    assert r.status_code == 409  # no receiver configured in this build
    monkeypatch.setenv("HEALTH_SIGNAL_URL", "https://receiver.example/v1/report")
    r = client.put("/api/system/health-signal", headers=auth_headers, json={"enabled": True})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["available"] is True
    got = client.get("/api/system/health-signal", headers=auth_headers).json()
    assert got["preview"]["schema"] == 1 and len(got["preview"]["id"]) == 32
    assert (
        client.put("/api/system/health-signal", headers=auth_headers, json={"enabled": False}).json()["enabled"]
        is False
    )
