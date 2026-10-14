"""smartctl output parsing -> (temperature, health)."""

from backend.hardware.disks import _parse_self_test_info, _parse_smart, _short_name


def ata_report(temp=35, realloc=0, pending=0, offline=0, crc=0, passed=True):
    verdict = "PASSED" if passed else "FAILED!"
    return f"""smartctl 7.4 2023-08-01 r5530 [x86_64-linux] (local build)
=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: {verdict}

ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
  1 Raw_Read_Error_Rate     0x000b   100   100   016    Pre-fail  Always       -       0
  5 Reallocated_Sector_Ct   0x0033   100   100   005    Pre-fail  Always       -       {realloc}
  9 Power_On_Hours          0x0012   099   099   000    Old_age   Always       -       8123
194 Temperature_Celsius     0x0002   171   171   000    Old_age   Always       -       {temp} (Min/Max 20/45)
197 Current_Pending_Sector  0x0022   100   100   000    Old_age   Always       -       {pending}
198 Offline_Uncorrectable   0x0008   100   100   000    Old_age   Offline      -       {offline}
199 UDMA_CRC_Error_Count    0x000a   200   200   000    Old_age   Always       -       {crc}
"""


def ata_report_7col(temp=48, realloc=0, pending=0, offline=0, crc=0, passed=True):
    verdict = "PASSED" if passed else "FAILED!"
    return f"""smartctl 7.4 2023-08-01 r5530 [x86_64-linux] (local build)
=== START OF READ SMART DATA SECTION ===
SMART overall-health self-assessment test result: {verdict}

Vendor Specific SMART Attributes with Thresholds:
ID# ATTRIBUTE_NAME          FLAGS    VALUE WORST THRESH FAIL RAW_VALUE
  1 Raw_Read_Error_Rate     POSR--   082   064   044    -    143612000
  3 Spin_Up_Time            PO----   090   089   000    -    0
  4 Start_Stop_Count        -O--CK   100   100   020    -    821
  5 Reallocated_Sector_Ct   PO--CK   100   100   010    -    {realloc}
  7 Seek_Error_Rate         POSR--   079   060   045    -    85646179
  9 Power_On_Hours          -O--CK   098   098   000    -    2244
 10 Spin_Retry_Count        PO--C-   100   100   097    -    0
 12 Power_Cycle_Count       -O--CK   100   100   020    -    87
 18 Unknown_Attribute       PO-R--   100   100   050    -    0
187 Reported_Uncorrect      -O--CK   100   100   000    -    0
188 Command_Timeout         -O--CK   100   100   000    -    0
190 Airflow_Temperature_Cel -O---K   064   049   000    -    36 (Min/Max 28/40)
192 Power-Off_Retract_Count -O--CK   100   100   000    -    57
193 Load_Cycle_Count        -O--CK   100   100   000    -    850
194 Temperature_Celsius     -O---K   036   051   000    -    {temp} (0 20 0 0 0)
197 Current_Pending_Sector  -O--C-   100   100   000    -    {pending}
198 Offline_Uncorrectable   ----C-   100   100   000    -    {offline}
199 UDMA_CRC_Error_Count    -OSRCK   200   200   000    -    {crc}
200 Multi_Zone_Error_Rate   PO---K   100   100   001    -    0
"""


def nvme_report(temp=40, spare=100, spare_thresh=10, used=3, media_err=0, passed=True):
    verdict = "PASSED" if passed else "FAILED!"
    return f"""=== START OF SMART DATA SECTION ===
SMART overall-health self-assessment test result: {verdict}

SMART/Health Information (NVMe Log 0x02)
Critical Warning:                   0x00
Temperature:                        {temp} Celsius
Available Spare:                    {spare}%
Available Spare Threshold:          {spare_thresh}%
Percentage Used:                    {used}%
Data Units Read:                    12,345,678 [6.32 TB]
Media and Data Integrity Errors:    {media_err:,}
"""


def test_healthy_hdd():
    temp, health, _ = _parse_smart(ata_report(temp=35), is_nvme=False)
    assert (temp, health) == (35, "ok")


def test_smartctl_x_7col_ironwolf_preserves_current_temp_over_lifetime_min():
    """
    Regression test for issue where opening and closing SMART modal for Seagate IronWolf
    drives caused telemetry to drop from 48C to 20C (lifetime minimum secondary sub-byte).
    """
    temp, health, metrics = _parse_smart(ata_report_7col(temp=48), is_nvme=False)
    assert temp == 48, f"Expected 48C current temp, but parsed lifetime min: {temp}"
    assert health == "ok"
    assert metrics["realloc"] == 0


def test_smartctl_x_7col_realloc_and_pending_extraction():
    _, health, metrics = _parse_smart(ata_report_7col(realloc=12, pending=4, crc=2), is_nvme=False)
    assert metrics["realloc"] == 12
    assert metrics["pending"] == 4
    assert metrics["crc"] == 2
    assert health == "crit"


def test_attribute_194_precedence_over_190():
    raw = """ID# ATTRIBUTE_NAME          FLAGS    VALUE WORST THRESH FAIL RAW_VALUE
190 Airflow_Temperature_Cel -O---K   064   049   000    -    32 (Min/Max 28/40)
194 Temperature_Celsius     -O---K   036   051   000    -    44 (0 22 0 0 0)
"""
    temp, health, _ = _parse_smart(raw, is_nvme=False)
    assert temp == 44, f"Expected core temp 44C from attr 194 to take precedence over airflow 32C, got {temp}"
    assert health == "ok"


def test_hdd_temperature_from_raw_column_ignores_min_max_suffix():
    temp, _, _ = _parse_smart(ata_report(temp=41), is_nvme=False)
    assert temp == 41


def test_hdd_warm_is_warning():
    temp, health, _ = _parse_smart(ata_report(temp=52), is_nvme=False)
    assert (temp, health) == (52, "warn")


def test_hdd_hot_is_critical():
    _, health, _ = _parse_smart(ata_report(temp=61), is_nvme=False)
    assert health == "crit"


def test_reallocated_sectors_warn():
    _, health, _ = _parse_smart(ata_report(realloc=8), is_nvme=False)
    assert health == "warn"


def test_crc_errors_warn():
    _, health, _ = _parse_smart(ata_report(crc=3), is_nvme=False)
    assert health == "warn"


def test_pending_sectors_critical():
    _, health, _ = _parse_smart(ata_report(pending=1), is_nvme=False)
    assert health == "crit"


def test_offline_uncorrectable_critical():
    _, health, _ = _parse_smart(ata_report(offline=2), is_nvme=False)
    assert health == "crit"


def test_failed_self_assessment_critical():
    _, health, _ = _parse_smart(ata_report(passed=False), is_nvme=False)
    assert health == "crit"


def test_healthy_nvme():
    temp, health, _ = _parse_smart(nvme_report(temp=40), is_nvme=True)
    assert (temp, health) == (40, "ok")


def test_nvme_normal_load_temp_not_warning():
    # 55°C triggers warning on HDD, but is normal operating range for NVMe
    _, health, _ = _parse_smart(nvme_report(temp=55), is_nvme=True)
    assert health == "ok"


def test_nvme_high_temp_warning():
    _, health, _ = _parse_smart(nvme_report(temp=71), is_nvme=True)
    assert health == "warn"


def test_nvme_critical_temp():
    _, health, _ = _parse_smart(nvme_report(temp=76), is_nvme=True)
    assert health == "crit"


def test_nvme_wear_warning():
    _, health, _ = _parse_smart(nvme_report(used=85), is_nvme=True)
    assert health == "warn"


def test_nvme_spare_below_threshold_critical():
    _, health, _ = _parse_smart(nvme_report(spare=5, spare_thresh=10), is_nvme=True)
    assert health == "crit"


def test_nvme_media_errors_with_thousands_separator_critical():
    _, health, _ = _parse_smart(nvme_report(media_err=1234), is_nvme=True)
    assert health == "crit"


def test_empty_output_is_unknown_but_ok():
    temp, health, _ = _parse_smart("", is_nvme=False)
    assert (temp, health) == (None, "ok")


def test_garbage_output_does_not_raise():
    temp, _, _ = _parse_smart("Temperature_Celsius ???\n\x00\x01 junk", is_nvme=False)
    assert temp is None


def test_short_names():
    assert _short_name("nvme1n1") == "nv1"
    assert _short_name("sda") == "sda"


def test_smart_no_medium_present():
    raw = (
        "smartctl 7.4 2023-08-01 r5530 [x86_64-linux] (local build)\n"
        "Read Device Identity failed: scsi error no medium present\n"
        "A mandatory SMART command failed: exiting."
    )
    temp, health, _ = _parse_smart(raw, is_nvme=False)
    assert temp is None
    assert health == "ok"


def test_standby_detection_differentiates_scsi_errors():
    standby_out = "smartctl 7.4\nDevice is in STANDBY mode, exit(2)"
    sleep_out = "smartctl 7.4\nDevice is in SLEEP mode, exit(2)"
    no_medium_out = "smartctl 7.4\nRead Device Identity failed: scsi error no medium present"
    unsupported_out = "smartctl 7.4\nRead Device Identity failed: scsi error unsupported scsi opcode"

    def is_standby(out):
        u = out.upper()
        return "DEVICE IS IN STANDBY" in u or "DEVICE IS IN SLEEP" in u

    assert is_standby(standby_out) is True
    assert is_standby(sleep_out) is True
    assert is_standby(no_medium_out) is False
    assert is_standby(unsupported_out) is False


def test_discover_disks_skips_zero_size(monkeypatch, tmp_path):
    import backend.hardware.disks as disks_mod
    from backend.state import Z_STATE

    fake_sys = tmp_path / "sys"
    block_dir = fake_sys / "block"
    block_dir.mkdir(parents=True)

    # Real drive sda with size
    sda = block_dir / "sda"
    sda.mkdir()
    (sda / "size").write_text("42970644480\n")
    (sda / "queue").mkdir()
    (sda / "queue" / "rotational").write_text("1\n")

    # Empty card slot sdc with size 0
    sdc = block_dir / "sdc"
    sdc.mkdir()
    (sdc / "size").write_text("0\n")
    (sdc / "queue").mkdir()
    (sdc / "queue" / "rotational").write_text("0\n")

    import backend.hardware.hal as hal_mod

    monkeypatch.setattr(
        hal_mod.DiskDiscoveryHAL,
        "discover_physical_disks",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("HAL fallback test")),
    )
    monkeypatch.setattr(disks_mod, "HOST_SYS", str(fake_sys))
    Z_STATE.cached_disk_list = None
    Z_STATE.cached_disk_list_time = 0.0

    discovered = disks_mod._discover_disks()
    dev_names = [d["dev"] for d in discovered]
    assert "sda" in dev_names
    assert "sdc" not in dev_names


def test_poll_disk_smart_exit_code_2_standby(monkeypatch):
    import subprocess
    import backend.hardware.disks as disks_mod
    from backend.state import Z_STATE

    class MockProcessResult:
        returncode = 2
        stdout = '{"smartctl": {"exit_status": 2, "messages": [{"string": "Device is in STANDBY mode, exit(2)"}]}}'
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: MockProcessResult())
    Z_STATE.cached_smart_data["sdb"] = (35, "ok")
    disks_mod.poll_disk_smart("sdb", is_nvme=False)

    temp, health = Z_STATE.cached_smart_data.get("sdb", (None, None))
    assert health == "standby"
    assert temp == 35  # Preserved previous temperature


def test_fetch_disk_smart_detail_standby_preservation(monkeypatch):
    import subprocess
    import backend.hardware.disks as disks_mod
    from backend.state import Z_STATE

    class MockStandbyProbe:
        returncode = 2
        stdout = "Device is in STANDBY mode"
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: MockStandbyProbe())
    # Ensure Popen is not called to spin up drive
    dd_called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: dd_called.append(args))

    Z_STATE.cached_smart_data["sdc"] = (32, "standby")
    detail = disks_mod.fetch_disk_smart_detail("sdc", wake_if_standby=False)

    assert detail["health"] == "STANDBY"
    assert detail["is_standby"] is True
    assert len(dd_called) == 0  # dd spin up was safely skipped!


def test_run_disk_smart_test_skip_if_standby():
    import backend.hardware.disks as disks_mod
    from backend.state import Z_STATE

    Z_STATE.cached_smart_data["sdd"] = (None, "standby")
    res = disks_mod.run_disk_smart_test("sdd", test_type="short", skip_if_standby=True)
    assert res["skipped"] is True
    assert res["success"] is False
    assert "standby mode" in res["output"].lower()


def test_parse_self_test_info_ata_in_progress():
    doc = {
        "ata_smart_data": {
            "self_test": {
                "status": {
                    "value": 244,
                    "string": "Self-test routine in progress... 40% of test remaining",
                    "passed": False,
                },
                "polling_minutes": {"short": 1, "extended": 180},
            }
        }
    }
    prog, log = _parse_self_test_info(doc, "")
    assert prog["in_progress"] is True
    assert prog["percent_remaining"] == 40
    assert prog["percent_completed"] == 60
    assert "40% of test remaining" in prog["status_text"]
    assert prog["polling_minutes"]["short"] == 1


def test_parse_self_test_info_ata_completed():
    doc = {
        "ata_smart_data": {
            "self_test": {
                "status": {
                    "value": 0,
                    "string": "Completed without error",
                    "passed": True,
                }
            }
        },
        "ata_smart_self_test_log": {
            "standard": {
                "count": 1,
                "table": [
                    {
                        "type": {"string": "Short offline"},
                        "status": {"string": "Completed without error", "passed": True},
                        "lifetime_hours": 2231,
                    }
                ],
            }
        },
    }
    prog, log = _parse_self_test_info(doc, "")
    assert prog["in_progress"] is False
    assert prog["percent_completed"] == 100
    assert len(log) == 1
    assert log[0]["num"] == 1
    assert log[0]["type"] == "Short offline"
    assert log[0]["passed"] is True
    assert log[0]["lifetime_hours"] == 2231


def test_parse_self_test_info_nvme_no_test_in_progress():
    raw_text = """
=== START OF SMART DATA SECTION ===
SMART overall-health self-assessment test result: PASSED

SMART Self-test log
Num  Test_Description    Status                  Power_on_Hours  Failing_LBA
  1  Short offline       Completed without error            120            -

Self-test status: No self-test in progress
"""
    prog, log = _parse_self_test_info({}, raw_text)
    assert prog["in_progress"] is False
    assert len(log) == 1
    assert log[0]["type"] == "Short offline"
    assert log[0]["passed"] is True


def test_parse_self_test_info_nvme_in_progress_json():
    from backend.hardware.disks import _parse_self_test_info

    doc = {
        "nvme_self_test_log": {
            "current_self_test_operation": {"value": 1, "string": "Short self-test in progress"},
            "current_self_test_completion_percent": 25,
            "table": [
                {
                    "self_test_code": {"value": 1, "string": "Short"},
                    "self_test_result": {"value": 0, "string": "Completed without error"},
                    "power_on_hours": 24,
                }
            ],
        }
    }
    prog, log = _parse_self_test_info(doc, "")
    assert prog["in_progress"] is True
    assert prog["percent_completed"] == 25
    assert prog["percent_remaining"] == 75
    assert prog["status_text"] == "Short self-test in progress"
    assert len(log) == 1
    assert log[0]["passed"] is True


def test_parse_self_test_info_nvme_in_progress_raw_text():
    from backend.hardware.disks import _parse_self_test_info

    raw_text = """
=== START OF SMART DATA SECTION ===
Self-test Log (NVMe Log 0x06)
Self-test status: Short self-test in progress (30% completed)
Num  Test_Description  Status                       Power_on_Hours  Failing_LBA  NSID Seg SCT Code
 0   Short             Completed without error                  24            -     -   -   -    -
"""
    prog, log = _parse_self_test_info({}, raw_text)
    assert prog["in_progress"] is True
    assert prog["percent_completed"] == 30
    assert prog["percent_remaining"] == 70


def test_get_smart_device_type_nvme_resolution():
    from backend.hardware.disks import _get_smart_device_type

    assert _get_smart_device_type("nvme2n1") == "nvme,0xffffffff"
    assert _get_smart_device_type("/dev/nvme0n1") == "nvme,0xffffffff"
    assert _get_smart_device_type("/host/dev/nvme1n1") == "nvme,0xffffffff"
    assert _get_smart_device_type("sda") == "sat"


def test_resolve_dev_path_handles_dev_and_host_dev():
    from backend.hardware.disks import _resolve_dev_path

    p1 = _resolve_dev_path("nvme2n1")
    p2 = _resolve_dev_path("/dev/nvme2n1")
    p3 = _resolve_dev_path("/host/dev/nvme2n1")
    assert p1 == p2 == p3
