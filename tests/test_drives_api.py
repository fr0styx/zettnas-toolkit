"""Drive Health's first page: GET /api/drives/health, and the history it judges sleeping drives on."""

import time

import pytest

from backend.api import drives

DISKS = [
    {"dev": "sda", "model": "Example HDD", "serial": "A1", "role": "data", "transport": "sata"},
    {"dev": "sdb", "model": "Example HDD", "serial": "B2", "role": "parity", "transport": "sata"},
    {"dev": "nvme0n1", "model": "Example NVMe", "serial": "N3", "role": "cache", "transport": "nvme"},
    {"dev": "sdc", "model": "Broken", "serial": "C4", "role": "data", "transport": "sata"},
]


@pytest.fixture
def fake_drives(monkeypatch):
    woke = []

    def detail(dev, wake):
        woke.append(wake)
        if dev == "sdc":
            raise OSError("smartctl went away")
        if dev == "sdb":  # asleep: judged on its history
            return {
                "dev": dev,
                "is_standby": True,
                "model": "SATA HDD (Standby)",
                "temp": 31,
                "drive_health": {
                    "verdict": "soon",
                    "label": "Replace soon",
                    "summary": "Parts of the disk could not be read",
                    "findings": [{"code": "unreadable_sectors"}],
                    "from_history": True,
                    "reading_ts": 1,
                },
            }
        return {
            "dev": dev,
            "is_standby": False,
            "model": f"{dev} live",
            "serial": "S",
            "temp": 35,
            "power_on_hours": 100,
            "drive_health": {"verdict": "ok", "label": "Healthy", "summary": "No sign of trouble.", "findings": []},
        }

    monkeypatch.setattr(drives, "_discover_disks", lambda: DISKS)
    monkeypatch.setattr(drives, "fetch_disk_smart_detail", detail)
    drives._cache.update(ts=0.0, data=None)
    yield woke
    drives._cache.update(ts=0.0, data=None)


def test_every_drive_worst_first_without_waking_any(client, auth_headers, fake_drives):
    r = client.get("/api/drives/health", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    devs = [d["dev"] for d in data["drives"]]
    assert devs[0] == "sdb"  # the one that needs replacing comes first
    assert set(devs) == {"sda", "sdb", "nvme0n1", "sdc"}
    assert fake_drives and not any(fake_drives)  # no drive was asked to wake
    sleeping = data["drives"][0]
    assert sleeping["asleep"] and sleeping["from_history"] and sleeping["model"] == "Example HDD"
    assert sleeping["power_on_hours"] is None  # not read while asleep
    broken = next(d for d in data["drives"] if d["dev"] == "sdc")
    assert broken["verdict"] == "unknown" and "smartctl went away" in broken["error"]
    assert data["counts"] == {"soon": 1, "ok": 2, "unknown": 1}


def test_results_are_kept_briefly_and_refresh_reads_again(client, auth_headers, fake_drives):
    client.get("/api/drives/health", headers=auth_headers)
    n = len(fake_drives)
    client.get("/api/drives/health", headers=auth_headers)
    assert len(fake_drives) == n
    client.get("/api/drives/health?refresh=1", headers=auth_headers)
    assert len(fake_drives) == 2 * n


def test_needs_a_storage_or_system_scope(client):
    assert client.get("/api/drives/health").status_code in (401, 403)


def test_history_samples_keep_the_highest_count_per_bucket():
    from backend import db

    db.init_db()
    now = int(time.time())
    for i, (age_h, realloc) in enumerate(((50, 1), (49, 3), (2, 4))):
        db._SMART_STORED.clear()
        db.log_smart_metrics(now - age_h * 3600, "sdz", 30.0 + i, {"realloc": realloc}, 100 + i)
    rows = db.get_smart_history_samples("sdz")
    assert [r["reallocated_sectors"] for r in rows][-1] == 4
    assert max(r["reallocated_sectors"] for r in rows if r["ts"] <= now - 49 * 3600) == 3
    assert db.get_smart_history_samples("nothing-here") == []


def test_the_detail_carries_a_verdict_even_for_a_drive_never_read(monkeypatch):
    from backend.hardware import disks

    monkeypatch.setattr(disks, "get_smart_history_samples", lambda dev: [])
    monkeypatch.setattr(disks, "get_smart_test_history", lambda dev, n: [])
    assert disks.drive_health_for("sdz", None)["verdict"] == "unknown"
    doc = {"device": {"protocol": "ATA"}, "smart_status": {"passed": False}}
    assert disks.drive_health_for("sdz", doc)["verdict"] == "now"

    def broken(dev):
        raise RuntimeError("db gone")

    monkeypatch.setattr(disks, "get_smart_history_samples", broken)
    assert disks.drive_health_for("sdz", doc)["verdict"] == "unknown"


def test_verdicts_are_remembered_and_refreshed_for_every_drive(monkeypatch):
    from backend.hardware import disks
    from backend.state import Z_STATE

    monkeypatch.setattr(Z_STATE, "drive_verdicts", {})
    disks.remember_verdict(
        "sdq",
        {
            "verdict": "soon",
            "summary": "Too hot",
            "findings": [{"severity": "watch", "kind": "info"}, {"severity": "soon", "kind": "cooling"}],
        },
    )
    assert Z_STATE.drive_verdicts["sdq"]["kind"] == "cooling"
    assert Z_STATE.drive_verdicts["sdq"]["verdict"] == "soon"

    seen = []
    monkeypatch.setattr(disks, "_discover_disks", lambda: [{"dev": "sda"}, {"dev": ""}, {"dev": "sdb"}])

    def fake(dev, wake):
        assert wake is False  # never wakes a sleeping drive
        seen.append(dev)
        if dev == "sdb":
            raise OSError("gone")
        return {}

    monkeypatch.setattr(disks, "fetch_disk_smart_detail", fake)
    assert disks.refresh_drive_verdicts() == 1
    assert seen == ["sda", "sdb"]
