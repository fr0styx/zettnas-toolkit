"""SET-06: two lists that lost what they held.

Opening the Backup page dropped every app backup whose file was not there at that moment and saved
the shorter list; an unmounted pool was enough. Saving a snapshot schedule through the form reset
the daily tier (and the lock) the form does not show."""

from unittest.mock import patch

import pytest

from backend.fsutil import atomic_write_json, read_json
from backend.services import app_backup
from backend.services import snapshot_service as snaps


def test_reading_the_app_backup_list_never_shortens_it(tmp_path):
    here = tmp_path / "app_plex_1.tar.gz"
    here.write_bytes(b"x" * 10)
    registry = tmp_path / "app_backups.json"
    records = [
        {"id": "app_plex_1", "app_name": "plex", "filename": here.name, "filepath": str(here), "created_at": 2},
        {
            "id": "app_gone_1",
            "app_name": "gone",
            "filename": "app_gone_1.tar.gz",
            "filepath": "/mnt/unmounted/x",
            "created_at": 1,
        },
    ]
    atomic_write_json(str(registry), records)
    with patch("backend.services.app_backup.APP_BACKUPS_REGISTRY_FILE", str(registry)):
        listed = app_backup.list_app_backups()
        by_id = {r["id"]: r for r in listed}
        assert by_id["app_plex_1"]["missing"] is False and by_id["app_plex_1"]["size_bytes"] == 10
        assert by_id["app_gone_1"]["missing"] is True
        assert len(app_backup.list_app_backups("gone")) == 1
    # the list on disk is what it was: both records, and no "missing" written into it
    assert read_json(str(registry), []) == records


@pytest.fixture
def schedules(tmp_path, monkeypatch):
    monkeypatch.setattr(snaps, "SCHEDULES_FILE", str(tmp_path / "schedules.json"))
    monkeypatch.setattr(snaps, "availability", lambda pal=None: (True, ""))
    monkeypatch.setattr(snaps, "_set_previous_versions", lambda share, on: None)
    return snaps


def test_a_save_that_leaves_the_daily_tier_out_keeps_it(schedules):
    schedules.save_schedule("photos", "hourly", 24, immutable_days=7, keep_daily=30)
    schedules.save_schedule("photos", "daily", 10)  # what the form sent: no daily number, no lock
    saved = next(s for s in schedules.list_schedules() if s["share"] == "photos")
    assert (saved["every"], saved["keep"], saved["keep_daily"], saved["immutable_days"]) == ("daily", 10, 30, 7)


def test_a_save_that_names_them_changes_them(schedules):
    schedules.save_schedule("photos", "hourly", 24, immutable_days=7, keep_daily=30)
    schedules.save_schedule("photos", "hourly", 24, immutable_days=0, keep_daily=0)
    saved = next(s for s in schedules.list_schedules() if s["share"] == "photos")
    assert (saved["keep_daily"], saved["immutable_days"]) == (0, 0)


def test_a_new_schedule_starts_without_them(schedules):
    schedules.save_schedule("docs", "daily", 14)
    saved = next(s for s in schedules.list_schedules() if s["share"] == "docs")
    assert (saved["keep_daily"], saved["immutable_days"]) == (0, 0)


def test_the_route_passes_what_it_was_sent(client, auth_headers, schedules):
    r = client.put(
        "/api/snapshots/schedules",
        json={"share": "photos", "every": "hourly", "keep": 24, "keep_daily": 30, "immutable_days": 7},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/snapshots/schedules", json={"share": "photos", "every": "daily", "keep": 10}, headers=auth_headers
    )
    assert r.status_code == 200
    saved = next(s for s in schedules.list_schedules() if s["share"] == "photos")
    assert (saved["keep"], saved["keep_daily"], saved["immutable_days"]) == (10, 30, 7)
