"""
Unit and integration tests for Zettlab D4 appliance detection and ZettOS storage pool discovery.
Verifies that:
1. ARM64 Device Tree model/compatible strings properly identify Zettlab D4.
2. eMMC boot flash (mmcblk0 / transport: mmc) is excluded from internal bay disk count (4 drives = D4).
3. StoragePlatformDetector correctly identifies ZettOS via mounts, filesystem flags, and chassis identity.
4. ZettOSStorageAdapter and GenericLinuxStorageAdapter discover real mdadm RAID arrays (md3) and bcache mounts
   without misreporting the 28.2GB eMMC rootfs overlay as a 4-disk data pool.
"""

import os
from unittest.mock import MagicMock, patch

from backend.hardware.chassis import ChassisEngine
from backend.hardware.hal import PhysicalDiskRecord
from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    PlatformType,
    StoragePlatformDetector,
    ZettOSStorageAdapter,
)
from backend.hardware.storage import detect_chassis_model


def make_disk(
    dev_name: str,
    size_bytes: int,
    transport: str = "sata",
    role: str = "data",
    model: str = "Generic",
    serial: str = "Unknown",
    removable: bool = False,
    is_rotational: bool = True,
) -> PhysicalDiskRecord:
    return PhysicalDiskRecord(
        dev_name=dev_name,
        canonical_id=f"{transport}-{model}_{serial}",
        dev_path=f"/dev/{dev_name}",
        size_bytes=size_bytes,
        transport=transport,
        role=role,
        model=model,
        serial=serial,
        removable=removable,
        is_rotational=is_rotational,
    )


def test_zettlab_d4_device_tree_model_detection():
    """Verifies that an ARM64 Device Tree indicating a Zettlab D4 resolves to 'd4'."""
    dt_content = "Zettlab D4 Quad-Bay NAS\0"
    with patch("backend.hardware.storage._read_dt_text", return_value=dt_content):
        with patch("backend.hardware.storage._read_dmi_text", return_value=""):
            result = detect_chassis_model(force=True)
            assert result == "d4"


def test_zettlab_d4_drive_count_excludes_emmc():
    """Verifies that eMMC boot flash (transport mmc, role os, or mmcblk) is not counted as a bay disk."""
    mock_disks = [
        make_disk("sdc", 16000000000000, transport="sata", role="data", model="TOSHIBA MG08ACA16TE", serial="1440A074"),
        make_disk("sdd", 16000000000000, transport="sata", role="data", model="TOSHIBA MG08ACA16TE", serial="1440A076"),
        make_disk("sde", 16000000000000, transport="sata", role="data", model="TOSHIBA MG08ACA16TE", serial="1440A079"),
        make_disk("sdf", 16000000000000, transport="sata", role="data", model="TOSHIBA MG08ACA16TE", serial="1440A081"),
        make_disk(
            "nvme0n1",
            4000000000000,
            transport="nvme",
            role="cache",
            model="Netac 4TB",
            serial="AA2024",
            is_rotational=False,
        ),
        make_disk(
            "mmcblk0", 31268536320, transport="mmc", role="os", model="MMC32G", serial="0x1234", is_rotational=False
        ),
    ]

    with patch("backend.hardware.storage.os.path.exists", return_value=False):
        with patch("backend.hardware.storage._read_dmi_text", return_value=""):
            with patch("backend.hardware.storage._read_dt_text", return_value=""):
                with patch("backend.hardware.hal.DiskDiscoveryHAL.discover_physical_disks", return_value=mock_disks):
                    chassis = detect_chassis_model(force=True)
                    assert chassis == "d4"


def test_chassis_engine_status_d4():
    """Verifies that ChassisEngine.get_chassis_status returns 4 total bays and d4 for Zettlab D4."""
    mock_disks = [
        make_disk("sdc", 16000000000000, transport="sata", role="data"),
        make_disk("sdd", 16000000000000, transport="sata", role="data"),
        make_disk("sde", 16000000000000, transport="sata", role="data"),
        make_disk("sdf", 16000000000000, transport="sata", role="data"),
        make_disk("mmcblk0", 31268536320, transport="mmc", role="os", is_rotational=False),
    ]

    with patch.object(ChassisEngine, "_read_dmi_product_name", return_value="Zettlab D4 Quad-Bay"):
        with patch("backend.hardware.chassis.DiskDiscoveryHAL.discover_physical_disks", return_value=mock_disks):
            status = ChassisEngine.get_chassis_status()
            assert status["chassis_model"] == "ZETTLAB D4"
            assert status["total_bays"] == 4
            assert status["chassis_label"] == "Zettlab D4 (4-Bay)"


def test_storage_platform_detector_identifies_zettos():
    """Verifies that StoragePlatformDetector detects ZettOS via release files or environment variables."""

    # 1. Via release files
    def mock_isfile(p):
        return p == "/etc/zettos-release"

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "", "ZETTNAS_OBSERVER_ADAPTER": ""}):
        with patch("backend.hardware.pal_storage._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", side_effect=mock_isfile):
                plat = StoragePlatformDetector.detect()
                assert plat == PlatformType.ZETTOS

    # 2. Via explicit environment override
    with patch.dict(os.environ, {"ZETTNAS_OBSERVER_ADAPTER": "zettos"}):
        plat = StoragePlatformDetector.detect()
        assert plat == PlatformType.ZETTOS


def test_zettos_adapter_discovers_mdstat_raid5_and_bcache():
    """Verifies that ZettOSStorageAdapter discovers the 47.7TB RAID5 array and bcache pool."""
    adapter = ZettOSStorageAdapter(pool_path="/mnt/storage")

    mock_mdstat = {
        "md3": {
            "device": "md3",
            "state": "active",
            "level": "raid5",
            "members": ["sdc3", "sdf3", "sde3", "sdd3"],
            "blocks": 46562663424,
            "size_bytes": 46562663424 * 1024,  # ~47.7 TB
            "degraded": False,
        }
    }

    mock_mounts = [
        {"device": "/dev/bcache2", "mountpoint": "/app/data", "fstype": "btrfs", "options": "rw"},
    ]

    mock_hal_disks = [
        make_disk("sdc", 16000000000000, transport="sata", role="data"),
        make_disk("sdd", 16000000000000, transport="sata", role="data"),
        make_disk("sde", 16000000000000, transport="sata", role="data"),
        make_disk("sdf", 16000000000000, transport="sata", role="data"),
        make_disk("nvme0n1", 4000000000000, transport="nvme", role="cache", is_rotational=False),
    ]

    def mock_usage(path):
        if "app" in path or "data" in path or "bcache" in path:
            return MagicMock(total=3890000000000, used=1000000000000, free=2890000000000)
        return MagicMock(total=47700000000000, used=10000000000000, free=37700000000000)

    with patch.object(adapter, "_parse_mdstat", return_value=mock_mdstat):
        with patch.object(adapter, "_parse_mounts", return_value=mock_mounts):
            with patch("backend.hardware.hal.DiskDiscoveryHAL.discover_physical_disks", return_value=mock_hal_disks):
                with patch.object(adapter, "_is_os_overlay_or_emmc", return_value=False):
                    with patch("shutil.disk_usage", side_effect=mock_usage):
                        with patch.object(adapter, "_run_cmd", return_value=(1, "", "")):
                            pools = adapter.list_pools()

                            pool_ids = [p.id for p in pools]
                            assert "md3" in pool_ids
                            assert "bcache2" in pool_ids

                            md3_pool = next(p for p in pools if p.id == "md3")
                            assert md3_pool.fs_profile == "raid5"
                            assert md3_pool.total_bytes >= 40 * 1024 * 1024 * 1024 * 1024
                            assert len(md3_pool.members) == 4
                            assert md3_pool.status == "HEALTHY"


def test_generic_linux_adapter_guards_against_emmc_overlay():
    """Verifies that GenericLinuxStorageAdapter does not attach all physical disks to a 28GB eMMC overlay."""
    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")

    mock_mdstat = {
        "md3": {
            "device": "md3",
            "state": "active",
            "level": "raid5",
            "members": ["sdc3", "sdf3", "sde3", "sdd3"],
            "blocks": 46562663424,
            "size_bytes": 46562663424 * 1024,
            "degraded": False,
        }
    }

    with patch.object(adapter, "_parse_mdstat", return_value=mock_mdstat):
        with patch.object(adapter, "_parse_mounts", return_value=[]):
            with patch.object(adapter, "_is_os_overlay_or_emmc", return_value=True):
                with patch.object(adapter, "_run_cmd", return_value=(1, "", "")):
                    pools = adapter.list_pools()
                    pool_ids = [p.id for p in pools]
                    assert "md3" in pool_ids
                    assert "default_pool" not in pool_ids
