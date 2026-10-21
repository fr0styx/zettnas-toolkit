"""
Tests for Calendar Notes, Reminders, and iCal Provider Sync API.
Verifies CRUD operations, SSRF protection, iCal parsing, and .ics export.
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def mock_calendar_data(tmp_path, monkeypatch):
    data_file = str(tmp_path / "calendar_data.json")
    monkeypatch.setattr("backend.api.calendar.CALENDAR_DATA_FILE", data_file)
    monkeypatch.setattr("backend.api.calendar.DATA_DIR", str(tmp_path))
    yield


def test_get_events_empty(client, auth_headers):
    res = client.get("/api/calendar/events", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["events"] == []
    assert data["count"] == 0


def test_create_and_update_and_delete_note(client, auth_headers):
    # 1. Create a note
    payload = {
        "date": "2026-10-19",
        "time": "14:30",
        "title": "Review NAS Storage Backups",
        "description": "Check ZFS snapshots and remote sync",
        "type": "reminder",
        "category": "Work",
        "completed": False,
    }
    res = client.post("/api/calendar/notes", json=payload, headers=auth_headers)
    assert res.status_code == 200
    created = res.json()["note"]
    note_id = created["id"]
    assert created["title"] == "Review NAS Storage Backups"
    assert created["date"] == "2026-10-19"
    assert created["time"] == "14:30"
    assert created["completed"] is False

    # 2. Get events and verify presence
    res2 = client.get("/api/calendar/events?start_date=2026-10-01&end_date=2026-10-31", headers=auth_headers)
    assert res2.status_code == 200
    events = res2.json()["events"]
    assert len(events) == 1
    assert events[0]["id"] == note_id

    # 3. Patch note (mark complete)
    res_patch = client.patch(
        f"/api/calendar/notes/{note_id}",
        json={"completed": True, "title": "Review NAS Storage Backups [Done]"},
        headers=auth_headers,
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["note"]["completed"] is True
    assert res_patch.json()["note"]["title"] == "Review NAS Storage Backups [Done]"

    # 4. Delete note
    res_del = client.delete(f"/api/calendar/notes/{note_id}", headers=auth_headers)
    assert res_del.status_code == 200

    # 5. Verify deleted
    res3 = client.get("/api/calendar/events", headers=auth_headers)
    assert len(res3.json()["events"]) == 0


def test_feed_ssrf_protection(client, auth_headers):
    # Attempting to add loopback or metadata URL should fail
    bad_payload = {
        "name": "Evil Feed",
        "url": "http://127.0.0.1:8080/basic.ics",
        "color": "#ef4444",
        "provider": "google",
    }
    res = client.post("/api/calendar/feeds", json=bad_payload, headers=auth_headers)
    assert res.status_code == 400
    assert "disallowed" in res.json()["detail"].lower() or "invalid" in res.json()["detail"].lower()


def test_feed_sync_and_ical_parsing(client, auth_headers):
    sample_ics = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "PRODID:-//Google Inc//Google Calendar 70.9054//EN\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event123@google.com\r\n"
        "SUMMARY:Team Standup & Planning\r\n"
        "DESCRIPTION:Weekly sprint review\r\n"
        "DTSTART:20261019T150000Z\r\n"
        "DTEND:20261019T153000Z\r\n"
        "LOCATION:Conference Room A\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = sample_ics.encode("utf-8")
    mock_resp.headers.get_content_charset.return_value = "utf-8"
    mock_resp.__enter__.return_value = mock_resp

    with (
        patch("backend.api.calendar.validate_public_url", return_value=(True, "")),
        patch(
            "backend.services.safe_fetch.safe_fetch",
            return_value=(200, {"content-type": "text/calendar; charset=utf-8"}, sample_ics.encode("utf-8")),
        ),
    ):
        feed_payload = {
            "name": "Work Calendar",
            "url": "https://calendar.google.com/calendar/ical/test/basic.ics",
            "color": "#38bdf8",
            "provider": "google",
            "enabled": True,
        }
        res = client.post("/api/calendar/feeds", json=feed_payload, headers=auth_headers)
        assert res.status_code == 200
        feed = res.json()["feed"]
        feed_id = feed["id"]

        # Check events returned
        res_ev = client.get("/api/calendar/events", headers=auth_headers)
        assert res_ev.status_code == 200
        events = res_ev.json()["events"]
        assert len(events) == 1
        ev = events[0]
        assert ev["title"] == "Team Standup & Planning"
        assert ev["date"] == "2026-10-19"
        assert ev["time"] == "15:00"
        assert ev["source"] == "synced"
        assert ev["feed_name"] == "Work Calendar"

        # Check feeds endpoint
        res_feeds = client.get("/api/calendar/feeds", headers=auth_headers)
        assert res_feeds.status_code == 200
        feeds = res_feeds.json()["feeds"]
        assert len(feeds) == 1
        assert feeds[0]["event_count"] == 1

        # Delete feed
        res_del = client.delete(f"/api/calendar/feeds/{feed_id}", headers=auth_headers)
        assert res_del.status_code == 200

        # Verify synced events removed
        res_after = client.get("/api/calendar/events", headers=auth_headers)
        assert len(res_after.json()["events"]) == 0


def test_export_calendar_ics(client, auth_headers):
    # Create a note first
    client.post(
        "/api/calendar/notes",
        json={
            "date": "2026-10-25",
            "time": "09:00",
            "title": "System Maintenance",
            "description": "Apply firmware updates",
            "type": "task",
        },
        headers=auth_headers,
    )

    res = client.get("/api/calendar/export", headers=auth_headers)
    assert res.status_code == 200
    assert "text/calendar" in res.headers["content-type"]
    text = res.text
    assert "BEGIN:VCALENDAR" in text
    assert "SUMMARY:System Maintenance" in text
    assert "DTSTART:20261025T090000" in text
    assert "END:VCALENDAR" in text
