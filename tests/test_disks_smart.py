"""SMART parsing (JSON, text, SAS), health levels, degradation trends and the SMART poller."""

import json
import subprocess
import time

import pytest

from backend.hardware import disks
from backend.state import Z_STATE


def ata_doc(attrs=None):
    attrs = attrs or {}
    table = [{"id": k, "raw": {"value": v, "string": str(v)}} for k, v in attrs.items()]
    return {"smart_status": {"passed": True}, "ata_smart_attributes": {"table": table}}


class TestSmartJson:
    def test_healthy_hdd(self):
        temp, health, m = disks._parse_smart_json(
            {
                "smart_status": {"passed": True},
                "temperature": {"current": 36},
                "power_cycle_count": 120,
                "ata_smart_attributes": {
                    "table": [{"id": 5, "raw": {"value": 0}}, {"id": 241, "raw": {"value": 2_000_000_000}}]
                },
            },
            False,
        )
        assert (temp, health) == (36, "ok") and m["power_cycles"] == 120 and m["tbw_tb"] == 1.02

    def test_temperature_from_attribute_194_or_190(self):
        doc = ata_doc()
        doc["ata_smart_attributes"]["table"] = [
            {"id": 194, "raw": {"value": 0x2F0012002D, "string": "45 (Min/Max 18/47)"}}
        ]
        assert disks._parse_smart_json(doc, False)[0] == 45
        doc["ata_smart_attributes"]["table"] = [{"id": 190, "raw": {"value": 41, "string": ""}}]
        assert disks._parse_smart_json(doc, False)[0] == 41

    @pytest.mark.parametrize(
        "attrs, health", [({5: 8}, "warn"), ({199: 3}, "warn"), ({197: 1}, "crit"), ({198: 2}, "crit")]
    )
    def test_sector_counts(self, attrs, health):
        assert disks._parse_smart_json(ata_doc(attrs), False)[1] == health

    def test_failed_self_assessment(self):
        doc = ata_doc()
        doc["smart_status"]["passed"] = False
        assert disks._parse_smart_json(doc, False)[1] == "crit"

    def test_hot_hdd(self):
        doc = ata_doc()
        doc["temperature"] = {"current": 52}
        assert disks._parse_smart_json(doc, False)[1] == "warn"
        doc["temperature"] = {"current": 61}
        assert disks._parse_smart_json(doc, False)[1] == "crit"

    def test_nvme(self):
        log = {
            "temperature": 41,
            "available_spare": 100,
            "available_spare_threshold": 10,
            "percentage_used": 3,
            "media_errors": 0,
            "critical_warning": 0,
            "power_cycles": 77,
            "data_units_written": 10_000_000,
            "data_units_read": 20_000_000,
        }
        temp, health, m = disks._parse_smart_json({"nvme_smart_health_information_log": log}, True)
        assert (
            (temp, health) == (41, "ok")
            and m["critical_warning"] == "0x0"
            and m["tbw_tb"] == 5.12
            and m["power_cycles"] == 77
        )

    @pytest.mark.parametrize(
        "change, health",
        [({"percentage_used": 85}, "warn"), ({"media_errors": 2}, "crit"), ({"available_spare": 5}, "crit")],
    )
    def test_nvme_wear_and_errors(self, change, health):
        log = {"temperature": 40, "available_spare": 100, "available_spare_threshold": 10, **change}
        assert disks._parse_smart_json({"nvme_smart_health_information_log": log}, True)[1] == health

    def test_sas(self):
        doc = {
            "scsi_grown_defect_list": 4,
            "scsi_error_counter_log": {
                "read": {"total_un_corrected_errors": 1},
                "write": {"total_un_corrected_errors": 0},
            },
        }
        _, health, m = disks._parse_smart_json(doc, False)
        assert m["realloc"] == 4 and m["offline"] == 1 and health == "crit"

    def test_parse_dispatches_by_format(self):
        assert disks._parse_smart(json.dumps(ata_doc({5: 1})), False)[1] == "warn"
        assert disks._parse_smart(ata_doc(), False)[1] == "ok"
        assert disks._parse_smart("{broken", False)[1] == "ok"  # falls back to the text parser


SMART_X = """smartctl 7.4
SMART overall-health self-assessment test result: PASSED
ID# ATTRIBUTE_NAME          FLAGS    VALUE WORST THRESH FAIL RAW_VALUE
  5 Reallocated_Sector_Ct   PO--CK   100   100   010    -    2
194 Temperature_Celsius     -O---K   064   045   000    -    36 (Min/Max 20/45)
197 Current_Pending_Sector  -O--C-   100   100   000    -    0
198 Offline_Uncorrectable   ----C-   100   100   000    -    0
199 UDMA_CRC_Error_Count    -O--CK   200   200   000    -    0
"""

SMART_A = """ID# ATTRIBUTE_NAME          FLAG     VALUE WORST THRESH TYPE      UPDATED  WHEN_FAILED RAW_VALUE
190 Airflow_Temperature_Cel 0x0022   063   050   045    Old_age   Always       -       37
197 Current_Pending_Sector  0x0012   100   100   000    Old_age   Always       -       8
"""

NVME_TEXT = """SMART overall-health self-assessment test result: PASSED
Critical Warning:                   0x00
Temperature:                        44 Celsius
Available Spare:                    100%
Available Spare Threshold:          10%
Percentage Used:                    2%
Data Units Read:                    1,234,567 [632 GB]
Data Units Written:                 2,345,678 [1.20 TB]
Power Cycles:                       1,024
Media and Data Integrity Errors:    0
"""


class TestSmartText:
    def test_smartctl_x(self):
        temp, health, m = disks._parse_smart_text(SMART_X, False)
        assert temp == 36 and health == "warn" and m["realloc"] == 2

    def test_smartctl_a_layout(self):
        temp, health, m = disks._parse_smart_text(SMART_A, False)
        assert temp == 37 and m["pending"] == 8 and health == "crit"

    def test_nvme(self):
        temp, health, m = disks._parse_smart_text(NVME_TEXT, True)
        assert (temp, health) == (44, "ok")
        assert (
            m["tbw_tb"] == 1.2 and m["tbr_tb"] == 0.62 and m["power_cycles"] == 1024 and m["critical_warning"] == "0x00"
        )

    def test_failed(self):
        assert disks._parse_smart_text("SMART overall-health self-assessment test result: FAILED!", False)[1] == "crit"

    @pytest.mark.parametrize(
        "cols, want",
        [
            (["5", "Reallocated_Sector_Ct", "PO--CK", "100", "100", "010", "-", "12"], 12),
            (["9", "Power_On_Hours", "0x0032", "090", "090", "000", "Old_age", "Always", "-", "9131"], 9131),
            (
                [
                    "194",
                    "Temperature_Celsius",
                    "0x0022",
                    "064",
                    "045",
                    "000",
                    "Old_age",
                    "Always",
                    "-",
                    "36",
                    "(Min/Max",
                    "20/45)",
                ],
                36,
            ),
            (["x"], 0),
        ],
    )
    def test_raw_value_layouts(self, cols, want):
        assert disks._extract_raw_val(cols) == want


class TestTrends:
    @pytest.fixture(autouse=True)
    def _files(self, tmp_path, monkeypatch):
        self.alerts = []
        monkeypatch.setattr(disks, "TRENDS_FILE", str(tmp_path / "trends.json"))
        monkeypatch.setattr(disks, "_smart_trends", None)
        monkeypatch.setattr(disks, "add_event", lambda *a, **k: None)
        monkeypatch.setattr(disks, "send_notification", lambda payload: self.alerts.append(payload["message"]))

    def test_first_reading_is_the_baseline(self):
        disks._evaluate_smart_trends("sda", {"realloc": 3, "nvme_used": None})
        assert self.alerts == []

    def test_growth_alerts(self, tmp_path):
        disks._evaluate_smart_trends("sda", {"realloc": 3, "pending": 1})
        disks._evaluate_smart_trends("sda", {"realloc": 5, "pending": 1, "nvme_used": 4})
        assert self.alerts == ["Reallocated Sectors increased from 3 to 5"]
        assert json.loads((tmp_path / "trends.json").read_text())["sda"]["realloc"] == 5

    def test_baseline_survives_a_restart(self, monkeypatch):
        disks._evaluate_smart_trends("nvme0n1", {"nvme_media_err": 1})
        monkeypatch.setattr(disks, "_smart_trends", None)
        disks._evaluate_smart_trends("nvme0n1", {"nvme_media_err": 4})
        assert self.alerts == ["NVMe Media Errors increased from 1 to 4"]


class TestDeviceResolution:
    def test_paths(self, tmp_path, monkeypatch):
        (tmp_path / "disk" / "by-id").mkdir(parents=True)
        (tmp_path / "disk" / "by-id" / "ata-WDC_X").write_text("")
        (tmp_path / "sda").write_text("")
        monkeypatch.setattr(disks, "HOST_DEV", str(tmp_path))
        assert disks._resolve_dev_path("sda") == str(tmp_path / "sda")
        assert disks._resolve_dev_path("/dev/sda") == str(tmp_path / "sda")
        assert disks._resolve_dev_path("/host/dev/sda") == str(tmp_path / "sda")
        assert disks._resolve_dev_path("ata-WDC_X") == str(tmp_path / "disk" / "by-id" / "ata-WDC_X")
        assert disks._resolve_dev_path("/nonexistent/sdz") == str(tmp_path / "sdz")

    def test_smartctl_device_type(self, monkeypatch):
        monkeypatch.setattr(
            Z_STATE,
            "cached_disk_list",
            [{"dev": "sdc", "smart_protocol": "scsi"}, {"dev": "nvme1n1", "smart_protocol": "nvme"}],
        )
        assert disks._get_smart_device_type("/dev/sda") == "sat"
        assert disks._get_smart_device_type("nvme0n1") == "nvme,0xffffffff"
        assert disks._get_smart_device_type("sdc") == "scsi"
        assert disks._get_smart_device_type("nvme1n1") == "nvme,0xffffffff"


@pytest.fixture
def smart(monkeypatch, tmp_path):
    monkeypatch.setattr(Z_STATE, "cached_smart_data", {})
    monkeypatch.setattr(Z_STATE, "cached_smart_time", {})
    monkeypatch.setattr(Z_STATE, "last_smart_scan", {})
    monkeypatch.setattr(Z_STATE, "cached_disk_list", None)
    monkeypatch.setattr(disks, "HOST_SYS", str(tmp_path / "sys"))
    monkeypatch.setattr(disks, "HOST_DEV", str(tmp_path / "dev"))
    monkeypatch.setattr(disks, "_evaluate_smart_trends", lambda dev, m: None)
    logged = []
    monkeypatch.setattr(disks, "log_smart_metrics", lambda *a: logged.append(a))
    answers = []

    def run(cmd, **kw):
        code, out, err = answers.pop(0) if answers else (1, "", "")
        return subprocess.CompletedProcess(cmd, code, out, err)

    monkeypatch.setattr(disks.subprocess, "run", run)
    return answers, logged, tmp_path


class TestPoll:
    def test_reads_and_caches(self, smart):
        answers, logged, _ = smart
        answers.append((0, json.dumps({"smart_status": {"passed": True}, "temperature": {"current": 38}}), ""))
        disks.poll_disk_smart("sda", False)
        assert Z_STATE.cached_smart_data["sda"] == (38, "ok") and logged

    def test_sleeping_disk_keeps_its_last_temperature(self, smart):
        answers, _, _ = smart
        Z_STATE.cached_smart_data["sda"] = (35, "ok")
        answers.append((2, "", "Device is in STANDBY mode, exit(2)"))
        disks.poll_disk_smart("sda", False)
        assert Z_STATE.cached_smart_data["sda"] == (35, "standby")

    def test_legacy_smartctl_without_json(self, smart):
        answers, _, _ = smart
        answers.append((1, "", "smartctl: unrecognized option '-j'"))
        answers.append((0, SMART_X, ""))
        disks.poll_disk_smart("sdb", False)
        assert Z_STATE.cached_smart_data["sdb"] == (36, "warn")

    def test_errors_keep_the_last_reading_for_a_while(self, smart):
        answers, _, _ = smart
        Z_STATE.cached_smart_data["sdc"] = (40, "ok")
        Z_STATE.cached_smart_time["sdc"] = time.time()
        answers.append((4, "", "read error"))
        disks.poll_disk_smart("sdc", False)
        assert Z_STATE.cached_smart_data["sdc"] == (40, "ok")
        Z_STATE.cached_smart_time["sdc"] = time.time() - 600
        answers.append((4, "", "read error"))
        disks.poll_disk_smart("sdc", False)
        assert Z_STATE.cached_smart_data["sdc"] == (None, "unknown")

    def test_removable_media_is_not_polled(self, smart):
        answers, _, tmp_path = smart
        (tmp_path / "sys" / "block" / "sdx").mkdir(parents=True)
        (tmp_path / "sys" / "block" / "sdx" / "removable").write_text("1")
        disks.poll_disk_smart("sdx", False)
        assert Z_STATE.cached_smart_data["sdx"] == (None, "ok")

    def test_poll_all_picks_due_disks(self, smart, monkeypatch):
        polled = []
        monkeypatch.setattr(
            disks,
            "_discover_disks",
            lambda: [
                {"dev": "sda", "role": "data"},
                {"dev": "nvme0n1", "role": "cache"},
                {"dev": "mmcblk0", "role": "os"},
            ],
        )
        monkeypatch.setattr(disks, "SHOW_OS_DISK", False)
        monkeypatch.setattr(disks, "poll_disk_smart", lambda dev, is_nv: polled.append((dev, is_nv)))
        disks.poll_all_disks_smart(force=True)
        assert sorted(polled) == [("nvme0n1", True), ("sda", False)]
        polled.clear()
        Z_STATE.cached_smart_data.update({"sda": (30, "ok"), "nvme0n1": (40, "ok")})
        Z_STATE.last_smart_scan.update({"sda": time.time(), "nvme0n1": time.time()})
        disks.poll_all_disks_smart()
        assert polled == []
