"""SET-06: a backup to a second Kiboto counts as a copy outside the box.

A buddy's destination is "rest:http://...". The Overview and "Getting started" both took it for a
copy on this NAS, so a household that backs up to another Kiboto was told it has no copy."""

import time

import pytest

from backend.services import getting_started, protection_status

BUDDY = "rest:http://attic.example-tailnet.ts.net:8000/kiboto-abc/"


@pytest.mark.parametrize(
    "location, kind",
    [
        (BUDDY, "nas"),
        ("sftp:backup@office-nas:/srv/restic", "nas"),
        ("rclone:b2:nas", "cloud"),
        ("/mnt/disks/usb1/backup", "usb"),
        ("/mnt/remotes/office_nas/backup", "nas"),
        ("/mnt/user/backups", "here"),
        ("", "here"),
    ],
)
def test_where_a_destination_is(location, kind):
    assert protection_status.kind_of(location) == kind
    assert getting_started._off_box(location) is (kind != "here")


def test_the_overview_counts_a_buddy(monkeypatch):
    from backend.services import offsite_backup

    repos = [{"id": "attic", "name": "Attic", "location": BUDDY, "last_backup": time.time() - 3600}]
    monkeypatch.setattr(offsite_backup, "list_repos", lambda: repos)
    monkeypatch.setattr("backend.services.backup_engine.get_backup_jobs", lambda: [])
    status = protection_status.status()
    assert status["level"] == "good" and status["copies"] == 1 and status["where"] == ["nas"]


def test_getting_started_counts_a_buddy(monkeypatch):
    from backend.services import offsite_backup

    monkeypatch.setattr("backend.services.backup_engine.get_backup_jobs", lambda: [])
    monkeypatch.setattr(
        offsite_backup,
        "list_repos",
        lambda: [{"id": "attic", "location": BUDDY, "last_backup": time.time(), "last_result": "ok"}],
    )
    assert getting_started._has_backup() is True
    monkeypatch.setattr(
        offsite_backup,
        "list_repos",
        lambda: [{"id": "same", "location": "/mnt/user/backups", "last_backup": time.time(), "last_result": "ok"}],
    )
    assert getting_started._has_backup() is False
