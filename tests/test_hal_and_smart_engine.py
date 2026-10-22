"""
Unit and integration tests for the Universal Hardware Abstraction Layer (HAL)
and Multi-Protocol SMART Telemetry Engine (Sprint 1).
"""

import json
from unittest.mock import MagicMock, patch

from backend.hardware.disks import VALID_DEV_PATTERN, _discover_disks, _resolve_dev_path
from backend.hardware.hal import DiskDiscoveryHAL, PhysicalDiskRecord
from backend.hardware.smart_engine import SmartTelemetryEngine


def test_valid_dev_pattern_supports_multiletter_and_canonical_ids():
    # Standard disks
    assert VALID_DEV_PATTERN.fullmatch("sda")
    assert VALID_DEV_PATTERN.fullmatch("sdb")
    assert VALID_DEV_PATTERN.fullmatch("sdz")
    # Systems with >26 drives (LSI HBAs, 24-bay chassis)
    assert VALID_DEV_PATTERN.fullmatch("sdaa")
    assert VALID_DEV_PATTERN.fullmatch("sdab")
    assert VALID_DEV_PATTERN.fullmatch("sdaaa")
    # NVMe
    assert VALID_DEV_PATTERN.fullmatch("nvme0n1")
    assert VALID_DEV_PATTERN.fullmatch("nvme12n1")
    # Virtualized / Cloud
    assert VALID_DEV_PATTERN.fullmatch("vda")
    assert VALID_DEV_PATTERN.fullmatch("xvda")
    # Canonical by-id strings
    assert VALID_DEV_PATTERN.fullmatch("ata-WDC_WD100EMAZ-00WJTA0_JEG12345")
    assert VALID_DEV_PATTERN.fullmatch("nvme-Samsung_SSD_980_PRO_2TB_S5GXNF0R123456")
    assert VALID_DEV_PATTERN.fullmatch("scsi-35000c500b1234567")

    # Invalid names
    assert not VALID_DEV_PATTERN.fullmatch("sda; rm -rf /")
    assert not VALID_DEV_PATTERN.fullmatch("sda|cat")
    assert not VALID_DEV_PATTERN.fullmatch("../etc/passwd")


def test_hal_discovers_disks_with_canonical_by_id_and_controllers():
    fake_lsblk_output = json.dumps(
        {
            "blockdevices": [
                {
                    "name": "sda",
                    "kname": "sda",
                    "path": "/dev/sda",
                    "type": "disk",
                    "tran": "sata",
                    "rota": True,
                    "size": 10000000000000,
                    "model": "WDC WD100EMAZ-00WJTA0",
                    "serial": "JEG12345",
                    "wwn": "0x5000cca25d123456",
                    "vendor": "WDC",
                    "mountpoint": None,
                    "children": [{"name": "sda1", "mountpoint": "/mnt/disk1"}],
                },
                {
                    "name": "sdaa",
                    "kname": "sdaa",
                    "path": "/dev/sdaa",
                    "type": "disk",
                    "tran": "sas",
                    "rota": True,
                    "size": 16000000000000,
                    "model": "ST16000NM001G",
                    "serial": "ZL20ABCD",
                    "wwn": "0x5000c500b1234567",
                    "vendor": "SEAGATE",
                    "mountpoint": None,
                },
                {
                    "name": "nvme0n1",
                    "kname": "nvme0n1",
                    "path": "/dev/nvme0n1",
                    "type": "disk",
                    "tran": "nvme",
                    "rota": False,
                    "size": 2000000000000,
                    "model": "Samsung SSD 980 PRO 2TB",
                    "serial": "S5GXNF0R123456",
                    "mountpoint": "/",
                },
            ]
        }
    )

    fake_by_id_map = {
        "sda": "/dev/disk/by-id/ata-WDC_WD100EMAZ-00WJTA0_JEG12345",
        "sdaa": "/dev/disk/by-id/scsi-35000c500b1234567",
        "nvme0n1": "/dev/disk/by-id/nvme-Samsung_SSD_980_PRO_2TB_S5GXNF0R123456",
    }

    with (
        patch("subprocess.run") as mock_run,
        patch.object(DiskDiscoveryHAL, "_read_by_id_links", return_value=fake_by_id_map),
        patch.object(
            DiskDiscoveryHAL,
            "_probe_controller_driver",
            side_effect=lambda kname: "mpt3sas" if kname == "sdaa" else ("nvme" if "nvme" in kname else "ahci"),
        ),
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_lsblk_output, stderr="")
        records = DiskDiscoveryHAL.discover_physical_disks(force=True)

        assert len(records) == 3

        # Check sda
        sda = next(r for r in records if r.dev_name == "sda")
        assert sda.canonical_id == "ata-WDC_WD100EMAZ-00WJTA0_JEG12345"
        assert sda.transport == "sata"
        assert sda.controller_driver == "ahci"
        assert sda.smart_protocol == "sat"
        assert sda.role == "data"
        assert "/mnt/disk1" in sda.mountpoints

        # Check sdaa (>26 disk on SAS HBA)
        sdaa = next(r for r in records if r.dev_name == "sdaa")
        assert sdaa.canonical_id == "scsi-35000c500b1234567"
        assert sdaa.transport == "sas"
        assert sdaa.controller_driver == "mpt3sas"
        assert sdaa.smart_protocol == "scsi"
        assert sdaa.role == "data"

        # Check nvme0n1 (OS disk)
        nvme = next(r for r in records if r.dev_name == "nvme0n1")
        assert nvme.role == "os"
        assert nvme.smart_protocol == "nvme"
        assert nvme.is_rotational is False


def test_smart_engine_spindown_safety_invariant():
    """Verify that a drive in standby/sleep returns cached values without spinning up the spindle."""
    with patch("subprocess.run") as mock_run:
        # Exit code 2 simulates smartctl -n standby indicating standby mode
        mock_run.return_value = MagicMock(returncode=2, stdout="Device is in STANDBY mode, exit(2)\n", stderr="")

        res = SmartTelemetryEngine.query_smart_telemetry("sdb", "/dev/sdb", protocol="sat", allow_wake=False)
        assert res["standby"] is True
        assert res["health"] == "standby"
        assert res["model"] == "Sleeping Platter"


def test_smart_engine_enterprise_sas_scsi_decoding():
    """Verify that enterprise SAS SCSI Log Pages (defect list & uncorrected errors) are decoded properly."""
    fake_sas_json = {
        "device": {"model_name": "ST16000NM001G"},
        "serial_number": "ZL20ABCD",
        "smart_status": {"passed": True},
        "temperature": {"current": 38},
        "scsi_grown_defect_list": 12,
        "scsi_error_counter_log": {"read": {"total_un_corrected_errors": 0}, "write": {"total_un_corrected_errors": 2}},
    }

    temp, health, metrics, model, serial, _ = SmartTelemetryEngine.decode_smart_json(
        fake_sas_json, is_nvme=False, protocol="scsi"
    )

    assert temp == 38
    assert model == "ST16000NM001G"
    assert serial == "ZL20ABCD"
    assert metrics["sas_grown_defects"] == 12
    assert metrics["realloc"] == 12
    assert metrics["offline"] == 2
    # Uncorrected write errors trigger critical health
    assert health == "crit"


def test_disks_discover_disks_integration_backward_compatibility():
    """Verify that backend.hardware.disks._discover_disks returns standard dicts expected by callers."""
    with patch.object(DiskDiscoveryHAL, "discover_physical_disks") as mock_discover:
        mock_discover.return_value = [
            PhysicalDiskRecord(
                dev_name="sda",
                canonical_id="ata-WDC_123",
                dev_path="/dev/sda",
                transport="sata",
                controller_driver="ahci",
                is_rotational=True,
                role="data",
                smart_protocol="sat",
            ),
            PhysicalDiskRecord(
                dev_name="nvme0n1",
                canonical_id="nvme-Samsung_456",
                dev_path="/dev/nvme0n1",
                transport="nvme",
                controller_driver="nvme",
                is_rotational=False,
                role="os",
                smart_protocol="nvme",
            ),
        ]

        from backend.state import Z_STATE

        Z_STATE.cached_disk_list = None
        Z_STATE.cached_disk_list_time = 0.0

        disks = _discover_disks()
        assert len(disks) == 2
        assert disks[0]["dev"] == "sda"
        assert disks[0]["role"] == "data"
        assert disks[0]["canonical_id"] == "ata-WDC_123"
        assert disks[1]["dev"] == "nvme0n1"
        assert disks[1]["role"] == "os"


def test_predictive_smart_velocity_and_linear_regression(tmp_path):
    import time

    from backend.db import compute_linear_regression_slope, init_db, log_smart_metrics, query_smart_velocity

    # 1. Closed-form linear regression unit assertions
    # Perfectly linear: y = 2x + 1
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [3.0, 5.0, 7.0, 9.0, 11.0]
    slope, r2 = compute_linear_regression_slope(xs, ys)
    assert slope == 2.0
    assert r2 == 1.0

    # Constant: y = 0
    ys_flat = [0.0, 0.0, 0.0, 0.0]
    slope_f, r2_f = compute_linear_regression_slope([1.0, 2.0, 3.0, 4.0], ys_flat)
    assert slope_f == 0.0

    # 2. Database integration test with power on hours
    init_db()
    dev = "sd_predictive_test"
    now = int(time.time())

    # Log 10 checkpoints with increasing reallocated sectors over power-on hours
    for i in range(10):
        t = now - (10 - i) * 3600
        poh = 1000 + (i * 100)
        realloc = i * 2  # 2 reallocated sectors per 100 POH
        log_smart_metrics(
            t,
            dev,
            temp=35.0,
            metrics={"realloc": realloc, "pending": 0, "offline": 0, "crc": 0, "nvme_used": 0},
            power_on_hours=poh,
        )

    res = query_smart_velocity(dev)
    assert res["dev"] == dev
    assert "predictive_velocity" in res
    pred = res["predictive_velocity"]
    assert pred["sample_points"] == 10
    # Slope should be ~20 sectors per 1000 POH (0.02 * 1000)
    assert pred["realloc_slope_per_1000h"] > 15.0
    assert pred["realloc_r2"] > 0.9
    assert pred["is_accelerating"] is True


def test_fetch_disk_smart_detail_wake_triggers_spinup_and_bypasses_standby_guard():
    """Verifies wake_if_standby=True triggers spinup and bypasses -n standby check."""
    from backend.hardware.disks import fetch_disk_smart_detail

    mock_standby_resp = MagicMock()
    mock_standby_resp.returncode = 2
    mock_standby_resp.stdout = "Device is in STANDBY mode, exit(2)"
    mock_standby_resp.stderr = ""

    mock_active_resp = MagicMock()
    mock_active_resp.returncode = 0
    mock_active_resp.stdout = json.dumps(
        {
            "model_name": "ST22000DM000-3Y6103",
            "serial_number": "ZXA0T9C8",
            "smart_status": {"passed": True},
            "temperature": {"current": 37},
            "power_on_time": {"hours": 1240},
        }
    )
    mock_active_resp.stderr = ""

    # Case 1: wake_if_standby=False -> Respects standby mode
    with patch("subprocess.run", return_value=mock_standby_resp) as mock_run:
        res = fetch_disk_smart_detail("sda", wake_if_standby=False)
        assert res["health"] == "STANDBY"
        assert res["is_standby"] is True
        assert res["model"] == "SATA HDD (Standby)"
        # smartctl called with -n standby
        call_args = mock_run.call_args[0][0]
        assert "-n" in call_args and "standby" in call_args

    # Case 2: wake_if_standby=True -> Bypasses standby guard, triggers spinup & returns live details
    with (
        patch("subprocess.Popen") as mock_popen,
        patch("subprocess.run", return_value=mock_active_resp) as mock_run_active,
    ):
        res = fetch_disk_smart_detail("sda", wake_if_standby=True)
        assert res["health"] == "PASSED"
        assert res["model"] == "ST22000DM000-3Y6103"
        assert res["serial"] == "ZXA0T9C8"
        # Verify dd or mdcmd was triggered
        assert mock_popen.called
        # Verify smartctl was called WITHOUT -n standby
        for call in mock_run_active.call_args_list:
            cmd = call[0][0]
            if "smartctl" in cmd[0]:
                assert "-n" not in cmd
