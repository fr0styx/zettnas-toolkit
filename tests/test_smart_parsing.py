"""smartctl output parsing -> (temperature, health)."""

from backend.hardware.disks import _parse_smart, _short_name


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
    assert _parse_smart(ata_report(temp=35), is_nvme=False) == (35, "ok")


def test_hdd_temperature_from_raw_column_ignores_min_max_suffix():
    temp, _ = _parse_smart(ata_report(temp=41), is_nvme=False)
    assert temp == 41


def test_hdd_warm_is_warning():
    assert _parse_smart(ata_report(temp=52), is_nvme=False) == (52, "warn")


def test_hdd_hot_is_critical():
    assert _parse_smart(ata_report(temp=61), is_nvme=False)[1] == "crit"


def test_reallocated_sectors_warn():
    assert _parse_smart(ata_report(realloc=8), is_nvme=False)[1] == "warn"


def test_crc_errors_warn():
    assert _parse_smart(ata_report(crc=3), is_nvme=False)[1] == "warn"


def test_pending_sectors_critical():
    assert _parse_smart(ata_report(pending=1), is_nvme=False)[1] == "crit"


def test_offline_uncorrectable_critical():
    assert _parse_smart(ata_report(offline=2), is_nvme=False)[1] == "crit"


def test_failed_self_assessment_critical():
    assert _parse_smart(ata_report(passed=False), is_nvme=False)[1] == "crit"


def test_healthy_nvme():
    assert _parse_smart(nvme_report(temp=40), is_nvme=True) == (40, "ok")


def test_nvme_wear_warning():
    assert _parse_smart(nvme_report(used=85), is_nvme=True)[1] == "warn"


def test_nvme_spare_below_threshold_critical():
    assert _parse_smart(nvme_report(spare=5, spare_thresh=10), is_nvme=True)[1] == "crit"


def test_nvme_media_errors_with_thousands_separator_critical():
    assert _parse_smart(nvme_report(media_err=1234), is_nvme=True)[1] == "crit"


def test_empty_output_is_unknown_but_ok():
    assert _parse_smart("", is_nvme=False) == (None, "ok")


def test_garbage_output_does_not_raise():
    assert _parse_smart("Temperature_Celsius ???\n\x00\x01 junk", is_nvme=False)[0] is None


def test_short_names():
    assert _short_name("nvme1n1") == "nv1"
    assert _short_name("sda") == "sda"
