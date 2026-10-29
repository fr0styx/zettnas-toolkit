"""Drive Health revamp: a drive's make-up from smartctl, its history and its life outlook from
the stored readings (no drive is touched for them)."""

import time

import pytest

from backend.services import drive_health as dh

DAY = 86400


def _samples(n=10, step_days=3, **grow):
    now = int(time.time())
    out = []
    for i in range(n):
        s = {"ts": now - (n - 1 - i) * step_days * DAY, "temp": 30 + (i % 3), "power_on_hours": 26000 + i * 72}
        for key, (start, per) in grow.items():
            s[key] = start + per * i
        out.append(s)
    return out


def test_read_smartctl_identity():
    doc = {
        "device": {"protocol": "ATA"},
        "model_name": "WDC WD80EFZZ",
        "firmware_version": "81.00A81",
        "user_capacity": {"bytes": 8001563222016},
        "rotation_rate": 5400,
        "power_cycle_count": 41,
        "form_factor": {"name": "3.5 inches"},
        "interface_speed": {"current": {"string": "6.0 Gb/s"}},
    }
    r = dh.read_smartctl(doc)
    assert dh.identity(r) == {
        "protocol": "ata",
        "capacity_bytes": 8001563222016,
        "rotation_rpm": 5400,
        "firmware": "81.00A81",
        "power_cycles": 41,
        "form_factor": "3.5 inches",
        "link": "6.0 Gb/s",
    }
    nv = dh.read_smartctl(
        {
            "device": {"protocol": "NVMe"},
            "nvme_smart_health_information_log": {"power_cycles": 9, "data_units_written": 1000, "percentage_used": 3},
            "sata_version": {"string": "x"},
        }
    )
    assert nv["power_cycles"] == 9 and nv["written_bytes"] == 512000000
    assert dh.identity({**r, "from_history_ts": 1}) == {}


def test_assess_carries_identity():
    r = dh.read_smartctl(
        {
            "device": {"protocol": "NVMe"},
            "nvme_smart_health_information_log": {"percentage_used": 1},
            "firmware_version": "F1",
        }
    )
    assert dh.assess(r)["identity"]["firmware"] == "F1"


def test_history_view():
    s = _samples(crc_errors=(0, 1), pending_sectors=(0, 0))
    h = dh.history_view(s)
    assert h["temp"]["min"] == 30 and h["temp"]["max"] == 32 and h["temp"]["now"] == s[-1]["temp"]
    assert set(h["counters"]) == {"crc_errors"}  # counters that never left zero aren't sent
    assert h["counters"]["crc_errors"]["first"] == 0 and h["counters"]["crc_errors"]["last"] == 9
    assert h["days"] == 27.0 and h["samples"] == 10
    assert dh.history_view([]) == {"temp": None, "counters": {}, "days": 0, "samples": 0}
    assert dh.history_view([{"ts": 1, "temp": None}])["temp"] is None


def test_life_outlook_nvme_wear_rate():
    s = _samples(n=11, step_days=3, nvme_pct_used=(10, 0.2))  # 10% -> 12% over 30 days
    for x in s:
        x["nvme_pct_used"] = int(round(x["nvme_pct_used"]))
    life = dh.life_outlook(s)
    assert life["wear_pct"] == 12 and life["wear_per_year"] == pytest.approx(24.3, abs=0.5)
    assert life["years_left"] == pytest.approx(88 / life["wear_per_year"], abs=0.1)
    assert life["age_years"] == round(max(x["power_on_hours"] for x in s) / 8766, 1)


def test_life_outlook_waits_for_real_change():
    flat = _samples(nvme_pct_used=(5, 0))
    assert dh.life_outlook(flat)["years_left"] is None
    short = _samples(n=3, step_days=1, nvme_pct_used=(5, 1))  # moved, but over two days only
    assert dh.life_outlook(short)["years_left"] is None
    hdd = dh.life_outlook(_samples())
    assert "wear_pct" not in hdd and hdd["age_years"] > 2
    assert dh.life_outlook([]) == {"age_years": None}


def test_history_endpoint(client, auth_headers, monkeypatch):
    from backend import db

    seen = []
    monkeypatch.setattr(
        db,
        "get_smart_history_samples",
        lambda dev, days, bucket_secs: seen.append((dev, days, bucket_secs)) or _samples(crc_errors=(0, 1)),
    )
    res = client.get("/api/drives/history?dev=/dev/sdb&days=90", headers=auth_headers).json()
    assert seen == [("sdb", 45, 45 * DAY // 120)]
    assert res["history"]["counters"]["crc_errors"]["last"] == 9 and res["life"]["age_years"]
    assert client.get("/api/drives/history?dev=../etc", headers=auth_headers).status_code == 400
