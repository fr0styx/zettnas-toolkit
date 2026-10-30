"""Drive Health: a drive's own temperature limit, every S.M.A.R.T. value over time, and the
drives that were taken out."""

import time

import pytest

from backend import db
from backend.services import drive_alerts, drive_health, drive_notes, drive_registry


@pytest.fixture(autouse=True)
def files(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_notes, "NOTES_FILE", str(tmp_path / "drive_notes.json"))
    monkeypatch.setattr(drive_registry, "SEEN_FILE", str(tmp_path / "drive_seen.json"))


# --- the temperature limit ---------------------------------------------------------------------


def test_the_limit_is_kept_with_the_details():
    assert drive_notes.save("nv-1", temp_limit="75") == {"temp_limit": 75}
    assert drive_notes.temp_limit_for("NV-1 ") == 75
    assert drive_notes.temp_limit_for("other", "") is None
    assert drive_notes.temp_limit_for() is None
    assert drive_notes.temp_limits_for_devs({"nvme0n1": "NV-1", "sda": "X"}) == {"nvme0n1": 75}
    for bad, why in (("hot", "whole number"), (25, "between 30 and 90"), (95, "between 30 and 90")):
        with pytest.raises(drive_notes.BadNotes, match=why):
            drive_notes.save("nv-1", temp_limit=bad)


def test_the_rules_use_the_drives_own_limit():
    r = {"protocol": "ata", "temp_c": 47, "attributes": {}}
    assert drive_health.temp_limits(r, False) == (50, 60)
    assert not [f for f in drive_health.findings_for(r) if f["kind"] == "cooling"]
    r["temp_limit"] = 45
    assert drive_health.temp_limits(r, False) == (45, 55)
    warm = [f for f in drive_health.findings_for(r) if f["kind"] == "cooling"]
    assert warm[0]["code"] == "warm" and warm[0]["params"]["limit"] == 45
    assert drive_health.temp_limits({"temp_limit": 200}, True) == (70, 80)


def test_alerts_use_the_drives_own_limit():
    drive_alerts._hot.clear()
    sent = []
    send = lambda **k: sent.append(k)  # noqa: E731
    drives = [{"dev": "lim-a", "temp": 47}, {"dev": "lim-b", "temp": 47, "is_nvme": True}]
    assert drive_alerts.check_temperatures(drives, 50, send, limits={"lim-a": 45}) == ["lim-a"]
    assert sent[0]["level"] == "warning"
    drives[0]["temp"] = 56  # 10 °C over its own limit: too hot
    assert drive_alerts.check_temperatures(drives, 50, send, limits={"lim-a": 45}) == ["lim-a"]
    assert sent[-1]["level"] == "critical"
    drive_alerts._hot.clear()


def test_the_api_takes_the_limit(client, auth_headers):
    r = client.put("/api/drives/notes", headers=auth_headers, json={"serial": "S7", "temp_limit": 55})
    assert r.status_code == 200 and r.json()["notes"] == {"temp_limit": 55}
    assert (
        client.put("/api/drives/notes", headers=auth_headers, json={"serial": "S7", "temp_limit": 20}).status_code
        == 422
    )


def test_the_hardware_layer_passes_limit_and_values(monkeypatch):
    from backend.hardware import disks

    monkeypatch.setattr(
        disks,
        "_discover_disks",
        lambda: [{"dev": "sdz", "serial": "Z9"}, {"dev": "sdy", "serial": "Hidden while in standby"}],
    )
    assert disks.drive_serials_by_dev() == {"sdz": "Z9"}
    drive_notes.save("Z9", temp_limit=40)
    stored = []
    monkeypatch.setattr(disks, "log_smart_attributes", lambda ts, serial, rows: stored.append((serial, rows)))
    monkeypatch.setattr(disks, "remember_verdict", lambda *a: None)
    doc = {
        "device": {"protocol": "ATA"},
        "serial_number": "Z9",
        "temperature": {"current": 42},
        "smart_status": {"passed": True},
        "ata_smart_attributes": {
            "table": [
                {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "worst": 99, "thresh": 10, "raw": {"value": 0}}
            ]
        },
    }
    result = disks.drive_health_for("sdz", doc)
    assert any(f["code"] == "warm" for f in result["findings"])
    assert stored[0][0] == "Z9" and stored[0][1][0] == {
        "attr": "5",
        "name": "Reallocated_Sector_Ct",
        "value": 100,
        "worst": 99,
        "thresh": 10,
        "raw": 0,
    }


# --- every value over time ---------------------------------------------------------------------


def test_attribute_rows_cover_ata_and_nvme():
    rows = drive_health.attribute_rows(
        {
            "attributes": {9: {"name": "Power_On_Hours", "value": 90, "worst": 90, "thresh": 0, "raw": 1200}},
            "nvme": {"media_errors": 0, "available_spare": 100, "flag": True},
        }
    )
    assert [r["attr"] for r in rows] == ["9", "nvme.available_spare", "nvme.media_errors"]


def test_values_are_stored_when_they_move_or_every_six_hours():
    db.init_db()
    db._ATTRS_STORED.clear()
    serial = f"VAL-{time.time_ns()}"
    t0 = int(time.time()) - 3 * 86400

    def row(raw):
        return [{"attr": "5", "name": "Reallocated_Sector_Ct", "value": 100, "worst": 100, "thresh": 10, "raw": raw}]

    assert db.log_smart_attributes(t0, serial, row(0)) is True
    assert db.log_smart_attributes(t0 + 60, serial, row(0)) is False  # nothing moved
    assert db.log_smart_attributes(t0 + 120, serial, row(2)) is True  # it moved
    assert db.log_smart_attributes(t0 + 120 + db.ATTR_EVERY_SECS, serial, row(2)) is True  # six hours on
    db._ATTRS_STORED.clear()  # after a restart the stored row is compared instead
    assert db.log_smart_attributes(t0 + 180 + db.ATTR_EVERY_SECS, serial, row(2)) is False
    hist = db.get_smart_attribute_history(serial, days=30)
    assert hist["5"]["raw"] == 2 and [p[1] for p in hist["5"]["points"]] == [0, 2, 2]
    assert db.log_smart_attributes(t0, "", row(0)) is False
    assert db.get_smart_attribute_history("nobody") == {}


def test_the_values_api(client, auth_headers):
    assert client.get("/api/drives/attributes?serial=../x", headers=auth_headers).status_code == 400
    r = client.get("/api/drives/attributes?serial=NOPE&days=500", headers=auth_headers)
    assert r.status_code == 200 and r.json() == {"serial": "NOPE", "days": 90, "attributes": {}}


# --- the drives taken out ----------------------------------------------------------------------


def test_drives_are_remembered_and_listed_when_gone():
    t0 = 1_800_000_000
    d = {
        "serial": "r-1",
        "model": "IronWolf",
        "dev": "sdb",
        "capacity_bytes": 4e12,
        "verdict": "watch",
        "label_key": "watch",
    }
    assert drive_registry.note_present([d, {"serial": "Hidden while in standby"}], now=t0) is True
    assert drive_registry.note_present([d], now=t0 + 60) is False  # nothing new within the hour
    assert drive_registry.note_present([{**d, "verdict": "unknown", "label_key": "unknown"}], now=t0 + 120) is False
    assert drive_registry.note_present([{**d, "dev": "sdc"}], now=t0 + 180) is True  # it moved
    assert drive_registry.note_present([d], now=t0 + 4000) is True  # an hour on
    assert drive_registry.taken_out(["R-1"]) == []
    gone = drive_registry.taken_out([])
    assert gone[0]["model"] == "IronWolf" and gone[0]["verdict"] == "watch" and gone[0]["first_seen"] == t0
    assert drive_registry.forget("r-1") is True and drive_registry.forget("r-1") is False


def test_a_broken_registry_starts_empty(tmp_path):
    (tmp_path / "drive_seen.json").write_text("[")
    assert drive_registry.taken_out([]) == []


def test_the_taken_out_api(client, auth_headers, monkeypatch):
    from backend.api import drives

    monkeypatch.setattr(drives, "_disks", lambda: [{"dev": "sda", "serial": "HERE"}])
    drive_registry.note_present([{"serial": "HERE", "model": "A"}, {"serial": "GONE", "model": "B"}])
    r = client.get("/api/drives/retired", headers=auth_headers)
    assert [d["model"] for d in r.json()["drives"]] == ["B"]
    r = client.post("/api/drives/retired/forget", headers=auth_headers, json={"serial": "gone"})
    assert r.json() == {"forgotten": True}
