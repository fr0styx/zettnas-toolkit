"""
Unit and integration tests for the Universal Hardware Abstraction Layer (HAL)
and Multi-Protocol SMART Telemetry Engine (Sprint 1).
"""

import json
from unittest.mock import MagicMock, patch
from backend.hardware.hal import DiskDiscoveryHAL, PhysicalDiskRecord
from backend.hardware.smart_engine import SmartTelemetryEngine
from backend.hardware.disks import _discover_disks, _resolve_dev_path, VALID_DEV_PATTERN


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
