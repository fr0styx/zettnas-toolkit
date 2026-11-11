"""
Unit and integration tests for Dynamic Chassis Engine and Multi-Tier Drive Locator (Sprint 2).
"""

import json
from unittest.mock import MagicMock, patch

from backend.hardware.chassis import BaySlotMapping, ChassisBayMapRequest, ChassisEngine
from backend.hardware.hal import PhysicalDiskRecord
from backend.hardware.locate import locate_drive_multitier


def test_without_an_enclosure_light_the_drives_own_light_flickers_by_real_reads():
    """SET-09: the reads go past the system's cache and move over the drive. Block 0 through the
    cache was answered from memory on a drive in use, so nothing flickered."""
    import os

    from backend.hardware import locate

    seen = {"flags": [], "offsets": []}

    def fake_open(path, flags):
        seen["flags"].append(flags)
        return 7

    def fake_preadv(fd, bufs, offset):
        seen["offsets"].append(offset)
        return locate.BLOCK

    started = []
    with (
        patch("os.path.exists", return_value=False),
        patch("os.open", side_effect=fake_open),
        patch("os.close"),
        patch("os.preadv", side_effect=fake_preadv),
        patch.object(locate.time, "sleep"),
        # the reads run in a thread; here it must not outlive these stand-ins (it would close a real file)
        patch.object(locate.threading, "Thread", side_effect=lambda **kw: started.append(kw) or MagicMock()),
    ):
        res = locate_drive_multitier("sda", "/dev/sda", duration_sec=2)
        assert len(started) == 1
        assert res == {"success": True, "tier": "strobe", "method": "activity_light", "dev": "sda", "duration": 2}
        assert locate._flicker("/dev/sda", 0.05) >= 1
    assert os.O_DIRECT in [f & os.O_DIRECT for f in seen["flags"]]
    assert seen["offsets"][0] == 0 and all(o % locate.BLOCK == 0 for o in seen["offsets"])
    if len(seen["offsets"]) > 1:
        assert len(set(seen["offsets"])) > 1  # not the same block again and again


def test_a_drive_that_can_not_be_read_is_said_and_a_sleeping_one_is_not_read_unasked():
    with patch("os.path.exists", return_value=False), patch("os.open", side_effect=OSError(5, "Input/output error")):
        res = locate_drive_multitier("sdx", "/dev/sdx", duration_sec=2)
    assert res["success"] is False and "could not be read" in res["error"]
    with patch("os.path.exists", return_value=False), patch("os.open") as opened:
        res = locate_drive_multitier("sdy", "/dev/sdy", duration_sec=2, allow_read_strobe=False)
    assert res == {"success": False, "needs_wake": True, "dev": "sdy"} and not opened.called


def test_the_light_bar_is_left_alone():
    """It flashed the same for every drive, which finds none, and was left white afterwards."""
    from backend.hardware import locate

    assert not hasattr(locate, "send_led_packet") and not hasattr(locate, "find_led_port")


def test_locate_drive_tier1_ses():
    """Verify that Tier 1 ledctl is invoked when /usr/sbin/ledctl is available."""
    with patch("os.path.exists", side_effect=lambda p: p == "/usr/sbin/ledctl"), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        res = locate_drive_multitier("sdb", "/dev/sdb", duration_sec=2)
        assert res["success"] is True
        assert res["tier"] == "ses"
        assert res["method"] == "bay_light"


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
        # no board, SKU, vendor or device-tree model either: a fake /sys another test filled
        # (a Zettlab D8, say) would make this an 8-bay chassis (seen in random order)
        patch("backend.hardware.chassis.ChassisEngine._read_dmi_field", return_value=""),
        patch("backend.hardware.storage._read_dt_text", return_value=""),
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
