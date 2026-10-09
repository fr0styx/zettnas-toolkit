"""
Unit and integration tests for Dynamic Chassis Engine and Multi-Tier Drive Locator (Sprint 2).
"""

import json
from unittest.mock import MagicMock, patch
from backend.hardware.chassis import ChassisEngine, ChassisBayMapRequest, BaySlotMapping
from backend.hardware.locate import locate_drive_multitier
from backend.hardware.hal import PhysicalDiskRecord


def test_locate_drive_tier3_strobe_fallback():
    """Verify that Tier 3 gentle read strobe executes when SES and ARGB are absent."""
    with (
        patch("os.path.exists", return_value=False),
        patch("backend.hardware.locate.find_led_port", return_value=None),
        patch("builtins.open", MagicMock()) as mock_open,
    ):
        res = locate_drive_multitier("sda", "/dev/sda", duration_sec=2)
        assert res["success"] is True
        assert res["tier"] == "strobe"
        assert res["method"] == "direct_read_activity"
        assert res["dev"] == "sda"


def test_locate_drive_tier1_ses():
    """Verify that Tier 1 ledctl is invoked when /usr/sbin/ledctl is available."""
    with patch("os.path.exists", side_effect=lambda p: p == "/usr/sbin/ledctl"), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res = locate_drive_multitier("sdb", "/dev/sdb", duration_sec=2)
        assert res["success"] is True
        assert res["tier"] == "ses"
        assert res["method"] == "ledctl"


def test_chassis_engine_auto_profile_classification():
    """Verify parametric layout profile selection based on drive count."""
    fake_disks = [
        PhysicalDiskRecord(
            dev_name=f"sd{chr(97 + i)}",
            canonical_id=f"ata-DISK_{i}",
            dev_path=f"/dev/sd{chr(97 + i)}",
            transport="sata",
            controller_driver="ahci",
            is_rotational=True,
            role="data",
        )
        for i in range(5)
    ]

    with (
        patch("backend.hardware.chassis.DiskDiscoveryHAL.discover_physical_disks", return_value=fake_disks),
        patch(
            "backend.hardware.chassis.ChassisEngine.load_bay_mapping_config",
            return_value={"profile": "auto", "mappings": []},
        ),
        patch("backend.hardware.chassis.ChassisEngine._read_dmi_product_name", return_value=""),
    ):
        status = ChassisEngine.get_chassis_status()
        assert status["profile"] == "tower_desktop"
        assert status["total_bays"] == 6
        assert len(status["bays"]) == 6
        # 5 populated, 1 vacant
        assert sum(1 for b in status["bays"] if b["is_populated"]) == 5
        assert sum(1 for b in status["bays"] if not b["is_populated"]) == 1


def test_chassis_engine_user_bay_slot_mapping(tmp_path):
    """Verify that user-configured slot mappings override sequential defaults."""
    fake_disks = [
        PhysicalDiskRecord(
            dev_name="sda",
            canonical_id="ata-WDC_123",
            dev_path="/dev/sda",
            transport="sata",
            controller_driver="ahci",
            is_rotational=True,
            role="data",
        ),
        PhysicalDiskRecord(
            dev_name="sdb",
            canonical_id="ata-SEAGATE_456",
            dev_path="/dev/sdb",
            transport="sata",
            controller_driver="ahci",
            is_rotational=True,
            role="data",
        ),
    ]

    # User maps SEAGATE to Slot 1 with a custom label, and WDC to Slot 2
    user_cfg = {
        "profile": "compact_dual",
        "total_bays": 2,
        "mappings": [
            {"slot_index": 1, "canonical_id": "ata-SEAGATE_456", "custom_label": "Parity Tray"},
            {"slot_index": 2, "canonical_id": "ata-WDC_123", "custom_label": "Data Tray 1"},
        ],
    }

    with (
        patch("backend.hardware.chassis.DiskDiscoveryHAL.discover_physical_disks", return_value=fake_disks),
        patch("backend.hardware.chassis.ChassisEngine.load_bay_mapping_config", return_value=user_cfg),
        patch("backend.hardware.chassis.ChassisEngine._read_dmi_product_name", return_value="Zettlab D4"),
    ):
        status = ChassisEngine.get_chassis_status()
        assert status["chassis_model"] == "ZETTLAB D4"
        assert status["total_bays"] == 2

        bay1 = status["bays"][0]
        assert bay1["slot_index"] == 1
        assert bay1["custom_label"] == "Parity Tray"
        assert bay1["disk"]["canonical_id"] == "ata-SEAGATE_456"

        bay2 = status["bays"][1]
        assert bay2["slot_index"] == 2
        assert bay2["custom_label"] == "Data Tray 1"
        assert bay2["disk"]["canonical_id"] == "ata-WDC_123"


def test_chassis_engine_save_bay_mapping(tmp_path):
    map_file = tmp_path / "bay_mapping.json"
    with patch("backend.hardware.chassis.CHASSIS_MAP_FILE", str(map_file)):
        req = ChassisBayMapRequest(
            profile="tower_desktop",
            total_bays=6,
            mappings=[BaySlotMapping(slot_index=1, canonical_id="ata-DISK_1", custom_label="Front Bay 1")],
        )
        res = ChassisEngine.save_bay_mapping(req)
        assert res["success"] is True

        assert map_file.exists()
        saved = json.loads(map_file.read_text())
        assert saved["profile"] == "tower_desktop"
        assert saved["total_bays"] == 6
        assert len(saved["mappings"]) == 1
        assert saved["mappings"][0]["custom_label"] == "Front Bay 1"
