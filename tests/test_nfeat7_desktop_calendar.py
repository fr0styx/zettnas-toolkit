"""NFEAT-7: the desktop calendar reads the family calendar from the office suite on this NAS."""

import pytest

from backend.services import family_dav

LINK = "webcal://192.168.1.5:8093/remote.php/dav/public-calendars/AbCdEf12GhIj?export"
READ_FROM = "http://192.168.1.5:8093/remote.php/dav/public-calendars/AbCdEf12GhIj?export"
ICS = (
    b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:1@family\r\nSUMMARY:Zahnarzt\r\n"
    b"DTSTART:20261110T080000Z\r\nDTEND:20261110T090000Z\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
)


@pytest.fixture(autouse=True)
def calendar_store(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.api.calendar.CALENDAR_DATA_FILE", str(tmp_path / "calendar_data.json"))
    monkeypatch.setattr("backend.api.calendar.DATA_DIR", str(tmp_path))


@pytest.fixture
def office(monkeypatch):
    found = {"name": "office-suite", "running": True, "port": 8093}
    monkeypatch.setattr(family_dav, "office_container", lambda: found)
    return found


@pytest.fixture
def fetched(monkeypatch):
    calls = []

    def fake(url, context="public", **_):
        calls.append((url, context))
        return 200, {"content-type": "text/calendar; charset=utf-8"}, ICS

    monkeypatch.setattr("backend.services.safe_fetch.safe_fetch", fake)
    return calls


def test_only_the_office_suites_subscription_link_is_read_at_home(office):
    assert family_dav.family_calendar_url(LINK) == READ_FROM
    assert family_dav.family_calendar_url(READ_FROM) == READ_FROM
    for other in (
        "webcal://192.168.1.5:8094/remote.php/dav/public-calendars/AbCdEf12GhIj?export",  # another port
        "http://192.168.1.5:8093/remote.php/dav/calendars/anna/personal",  # not a shared calendar
        "http://192.168.1.5:8093/remote.php/dav/public-calendars/short",  # not a share token
        "http://192.168.1.5/remote.php/dav/public-calendars/AbCdEf12GhIj",  # no port
        "ftp://192.168.1.5:8093/remote.php/dav/public-calendars/AbCdEf12GhIj",
        "http://192.168.1.5:99999/remote.php/dav/public-calendars/AbCdEf12GhIj",  # no such port
        "",
    ):
        assert family_dav.family_calendar_url(other) is None, other


def test_no_office_suite_no_exception(monkeypatch):
    monkeypatch.setattr(family_dav, "office_container", lambda: None)
    assert family_dav.family_calendar_url(LINK) is None


def test_the_family_calendar_is_added_and_synced_from_home(client, auth_headers, office, fetched):
    res = client.post("/api/calendar/feeds", json={"name": "Familie", "url": LINK}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["feed"]["provider"] == "family"
    assert fetched == [(READ_FROM, "lan")]
    events = client.get("/api/calendar/events?start_date=2026-11-01&end_date=2026-11-30", headers=auth_headers).json()
    assert [(ev["title"], ev["date"], ev["feed_name"]) for ev in events["events"]] == [
        ("Zahnarzt", "2026-11-10", "Familie")
    ]

    assert client.post("/api/calendar/sync", headers=auth_headers).status_code == 200
    assert fetched[-1] == (READ_FROM, "lan")


def test_other_home_addresses_stay_refused(client, auth_headers, office, fetched):
    res = client.post(
        "/api/calendar/feeds", json={"name": "x", "url": "http://192.168.1.5:8093/basic.ics"}, headers=auth_headers
    )
    assert res.status_code == 400
    assert fetched == []


def test_a_moved_office_suite_stops_the_exception(client, auth_headers, office, fetched):
    assert (
        client.post("/api/calendar/feeds", json={"name": "Familie", "url": LINK}, headers=auth_headers).status_code
        == 200
    )
    office["port"] = 8100  # the office suite now answers elsewhere: the old link is a plain home address
    feeds = client.post("/api/calendar/sync", headers=auth_headers).json()["feeds"]
    assert feeds[0]["error"].startswith("Security blocked")
    assert len(fetched) == 1
