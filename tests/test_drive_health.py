"""Drive Health rules (backend/services/drive_health.py): a verdict, the reason and what to do.

The drives below are written as smartctl prints them (JSON), following the patterns large drive
fleets see before a failure (pending and reallocated sectors that keep growing, a failed
self-test, an SSD out of spare blocks) and the ones that are not the drive's fault (cable
errors, heat). None of them is a real drive: models and serials are made up.
"""

from backend.services import drive_health as dh

NOW = 1_800_000_000
DAY = 86400


def ata(attrs=None, passed=True, temp=34, hours=12000, rpm=7200, tests=None, failing=()):
    table = []
    for aid, (name, raw, value) in (attrs or {}).items():
        table.append(
            {
                "id": aid,
                "name": name,
                "value": value,
                "worst": value,
                "thresh": 10,
                "when_failed": "now" if name in failing else "",
                "raw": {"value": raw},
            }
        )
    return {
        "device": {"protocol": "ATA"},
        "model_name": "Example HDD 8TB",
        "serial_number": "EX0001",
        "rotation_rate": rpm,
        "smart_status": {"passed": passed},
        "temperature": {"current": temp},
        "power_on_time": {"hours": hours},
        "ata_smart_attributes": {"table": table},
        "ata_smart_self_test_log": {"standard": {"table": tests or []}},
    }


def nvme(**log):
    base = {
        "critical_warning": 0,
        "available_spare": 100,
        "available_spare_threshold": 10,
        "percentage_used": 3,
        "media_errors": 0,
        "temperature": 41,
    }
    base.update(log)
    return {
        "device": {"protocol": "NVMe"},
        "model_name": "Example NVMe 1TB",
        "serial_number": "NV0001",
        "smart_status": {"passed": True},
        "power_on_time": {"hours": 900},
        "nvme_smart_health_information_log": base,
    }


def history(**series):
    """Samples over 40 days: each counter goes from its first to its last value."""
    rows = []
    for i, day in enumerate((40, 20, 10, 1)):
        row = {"ts": NOW - day * DAY}
        for k, (start, end) in series.items():
            row[k] = start if i == 0 else end
        rows.append(row)
    return rows


RECENT_TEST = [{"ts": NOW - 5 * DAY, "status": "passed", "test_type": "long"}]


def verdict(doc=None, hist=None, tests=RECENT_TEST):
    readings = dh.read_smartctl(doc) if doc is not None else None
    return dh.assess(readings, hist or [], tests, now=NOW)


def codes(v):
    return [f["code"] for f in v["findings"]]


def test_a_healthy_drive():
    v = verdict(ata({5: ("Reallocated_Sector_Ct", 0, 100), 197: ("Current_Pending_Sector", 0, 100)}))
    assert v["verdict"] == "ok" and v["label"] == "Healthy" and codes(v) == []


def test_old_reallocations_that_stand_still_are_only_watched():
    v = verdict(ata({5: ("Reallocated_Sector_Ct", 8, 100)}), history(reallocated_sectors=(8, 8)))
    assert v["verdict"] == "watch" and v["label"] == "Keep an eye on it"
    assert codes(v) == ["reallocated_stable"]
    assert "has not moved" in v["findings"][0]["detail"]


def test_reallocations_that_keep_growing_mean_replace_soon():
    v = verdict(ata({5: ("Reallocated_Sector_Ct", 40, 99)}), history(reallocated_sectors=(8, 40)))
    assert v["verdict"] == "soon" and v["label"] == "Replace soon"
    f = v["findings"][0]
    assert f["code"] == "reallocated_growing" and f["evidence"]["grew"] == 32
    assert "Copy what matters" in f["action"]


def test_unreadable_sectors_are_replace_soon_and_now_when_growing():
    doc = ata({197: ("Current_Pending_Sector", 16, 100), 198: ("Offline_Uncorrectable", 16, 100)})
    assert verdict(doc, history(pending_sectors=(16, 16)))["verdict"] == "soon"
    v = verdict(doc, history(pending_sectors=(2, 16)))
    assert v["verdict"] == "now" and v["label"] == "Replace now" and "getting worse" in v["summary"]


def test_a_failed_self_test_or_smart_status_means_replace_now():
    failed_test = [
        {
            "type": {"string": "Extended offline"},
            "status": {"string": "Completed: read failure", "passed": False},
            "lifetime_hours": 11990,
            "lba": 123456,
        }
    ]
    v = verdict(ata(tests=failed_test))
    assert v["verdict"] == "now" and codes(v)[0] == "self_test_failed"
    assert "read failure" in v["findings"][0]["detail"]
    assert verdict(ata(passed=False))["findings"][0]["code"] == "smart_failed"
    v = verdict(ata({5: ("Reallocated_Sector_Ct", 900, 5)}, failing=("Reallocated_Sector_Ct",)))
    assert "attribute_failing" in codes(v) and v["verdict"] == "now"


def test_cable_errors_are_not_the_drives_fault():
    v = verdict(ata({199: ("UDMA_CRC_Error_Count", 120, 200)}), history(crc_errors=(20, 120)))
    assert v["verdict"] == "watch" and codes(v) == ["cable_errors"]
    assert v["findings"][0]["kind"] == "cable" and "cable" in v["findings"][0]["action"].lower()
    old = verdict(ata({199: ("UDMA_CRC_Error_Count", 120, 200)}), history(crc_errors=(120, 120)))
    assert old["verdict"] == "ok" and codes(old) == ["cable_errors_old"]


def test_seagate_packed_timeouts_count_only_the_low_counter():
    v = verdict(ata({188: ("Command_Timeout", (5 << 32) | (5 << 16) | 3, 100)}))
    assert v["findings"][0]["evidence"]["command_timeouts"] == 3
    assert v["verdict"] == "ok"  # a few, long ago: not worth a warning
    assert verdict(ata({188: ("Command_Timeout", 250, 100)}))["verdict"] == "watch"


def test_heat_needs_attention_not_a_new_drive():
    v = verdict(ata(temp=62))
    assert v["verdict"] == "soon" and v["label"] == "Needs attention" and v["findings"][0]["kind"] == "cooling"
    assert verdict(ata(temp=53))["verdict"] == "watch"


def test_nvme_out_of_spare_blocks_degraded_or_read_only_means_replace_now():
    assert verdict(nvme(available_spare=5))["findings"][0]["code"] == "nvme_spare"
    assert verdict(nvme(critical_warning=0x04))["verdict"] == "now"
    v = verdict(nvme(critical_warning=0x08))
    assert v["verdict"] == "now" and "read-only" in v["summary"]


def test_nvme_wear_and_media_errors():
    assert verdict(nvme(percentage_used=85))["verdict"] == "watch"
    assert verdict(nvme(percentage_used=104))["verdict"] == "soon"
    assert verdict(nvme(media_errors=3), history(nvme_media_errors=(3, 3)))["verdict"] == "watch"
    assert verdict(nvme(media_errors=9), history(nvme_media_errors=(3, 9)))["verdict"] == "soon"


def test_ssd_life_left_on_sata_ssds():
    doc = ata({231: ("SSD_Life_Left", 0, 8)}, rpm=0)
    assert verdict(doc)["findings"][0]["code"] == "ssd_wear" and verdict(doc)["verdict"] == "soon"


def test_an_old_hard_drive_is_watched_but_an_old_ssd_is_not():
    assert "old_drive" in codes(verdict(ata(hours=6 * 8760)))
    assert "old_drive" not in codes(verdict(ata(hours=6 * 8760, rpm=0)))


def test_a_sleeping_drive_is_judged_from_its_last_reading():
    v = verdict(None, history(pending_sectors=(0, 4), reallocated_sectors=(0, 0)))
    assert v["from_history"] and v["verdict"] == "now" and codes(v)[0] == "unreadable_sectors"
    assert dh.assess(None, [], None)["verdict"] == "unknown"


def test_no_recent_self_test_is_a_hint_that_does_not_change_the_verdict():
    v = verdict(ata(), tests=[{"ts": NOW - 90 * DAY, "status": "passed"}])
    assert v["verdict"] == "ok" and codes(v) == ["no_recent_test"]
    assert verdict(ata(), tests=[])["verdict"] == "ok"


def test_growth_uses_the_sample_before_the_window():
    rows = [{"ts": NOW - 60 * DAY, "reallocated_sectors": 1}, {"ts": NOW - 2 * DAY, "reallocated_sectors": 5}]
    assert dh.growth(rows, NOW)["reallocated_sectors"] == 4
    assert dh.growth(rows[:1], NOW) == {}
    assert dh.growth([{"ts": NOW - 90 * DAY, "crc_errors": 1}, {"ts": NOW - 80 * DAY, "crc_errors": 2}], NOW) == {}


def test_every_finding_says_what_to_do():
    docs = [
        ata(passed=False),
        ata(temp=62),
        nvme(percentage_used=104),
        ata({10: ("Spin_Retry_Count", 2, 100)}),
        ata({184: ("End-to-End_Error", 1, 99)}),
        nvme(critical_warning=0x10),
    ]
    for doc in docs:
        for f in verdict(doc, tests=[])["findings"]:
            assert f["title"] and f["detail"] and f["action"], f
