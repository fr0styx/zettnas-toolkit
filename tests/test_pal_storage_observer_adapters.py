"""
ZettNAS Toolkit - Observer Mode PAL Adapters Unit & Integration Tests.
Verifies dedicated observer adapters for FygoOS, ZettOS, UGOS, and Generic Observer Mode.
Ensures zero-risk non-intrusive telemetry, disarmed mutations, and platform detection.
"""

import os
from unittest.mock import MagicMock, mock_open, patch

import pytest

from backend.hardware.pal_storage import (
    FygoOSStorageAdapter,
    GenericObserverStorageAdapter,
    ObserverStorageAdapter,
    PlatformCapabilityError,
    PlatformType,
    StoragePlatformDetector,
    UgosStorageAdapter,
    ZettOSStorageAdapter,
    get_storage_platform,
)

# ============================================================================
# 1. Capability & Instantiation Verification
# ============================================================================


def test_fygoos_adapter_capabilities():
    adapter = FygoOSStorageAdapter(pool_path="/media")
    assert adapter.get_platform_type() == PlatformType.FYGOOS
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_create_pools is False
    assert caps.can_destroy_pools is False
    assert caps.can_manage_shares is False
    assert caps.can_trigger_scrub is False
    assert caps.can_export_pools is False
    assert caps.can_import_pools is False
    assert "btrfs" in caps.supported_filesystems
    assert "ext4" in caps.supported_filesystems
    assert "f2fs" in caps.supported_filesystems
    assert "FygoOS" in caps.description


def test_zettos_adapter_capabilities():
    adapter = ZettOSStorageAdapter(pool_path="/mnt/user")
    assert adapter.get_platform_type() == PlatformType.ZETTOS
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_create_pools is False
    assert caps.can_destroy_pools is False
    assert caps.can_manage_shares is False
    assert caps.can_trigger_scrub is True
    assert caps.can_export_pools is False
    assert caps.can_import_pools is False
    assert "zfs" in caps.supported_filesystems
    assert "btrfs" in caps.supported_filesystems
    assert "ZettOS" in caps.description


def test_ugos_adapter_capabilities():
    adapter = UgosStorageAdapter(pool_path="/volume1")
    assert adapter.get_platform_type() == PlatformType.UGOS
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_create_pools is False
    assert caps.can_destroy_pools is False
    assert caps.can_manage_shares is False
    assert caps.can_trigger_scrub is True
    assert caps.can_export_pools is False
    assert caps.can_import_pools is False
    assert "btrfs" in caps.supported_filesystems
    assert "ext4" in caps.supported_filesystems
    assert "UGOS" in caps.description


def test_generic_observer_adapter_capabilities():
    adapter = GenericObserverStorageAdapter(pool_path="/mnt/storage")
    assert adapter.get_platform_type() == PlatformType.GENERIC_OBSERVER
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_create_pools is False
    assert caps.can_destroy_pools is False
    assert caps.can_manage_shares is False
    assert caps.can_trigger_scrub is False
    assert "btrfs" in caps.supported_filesystems
    assert "ext4" in caps.supported_filesystems
    assert "Observer Mode" in caps.description


# ============================================================================
# 2. Strict Disarmed Mutations (Observer Invariant)
# ============================================================================


@pytest.mark.parametrize(
    "adapter_cls",
    [
        FygoOSStorageAdapter,
        ZettOSStorageAdapter,
        UgosStorageAdapter,
        GenericObserverStorageAdapter,
    ],
)
def test_observer_adapters_strictly_forbid_mutations(adapter_cls):
    adapter = adapter_cls()

    # Pool creation
    with pytest.raises(PlatformCapabilityError) as exc_pool:
        adapter.create_pool("test_pool", ["/dev/sda"], fs_type="btrfs")
    assert "Observer mode active" in str(exc_pool.value)

    # Pool destruction
    with pytest.raises(PlatformCapabilityError) as exc_dest:
        adapter.destroy_pool("test_pool")
    assert "Observer mode active" in str(exc_dest.value)

    # Share creation
    with pytest.raises(PlatformCapabilityError) as exc_share:
        adapter.create_share("test_share", "/path/to/share")
    assert "Observer mode active" in str(exc_share.value)

    # Share deletion
    with pytest.raises(PlatformCapabilityError) as exc_del_share:
        adapter.delete_share("test_share")
    assert "Observer mode active" in str(exc_del_share.value)

    # Pool rename
    with pytest.raises(PlatformCapabilityError) as exc_rename:
        adapter.rename_pool("test_pool", "new_name")
    assert "Observer mode active" in str(exc_rename.value)

    # Snapshots
    with pytest.raises(PlatformCapabilityError) as exc_snap:
        adapter.create_snapshot("test_pool", "@shares", "snap1")
    assert "Observer mode active" in str(exc_snap.value)

    with pytest.raises(PlatformCapabilityError) as exc_snap_del:
        adapter.delete_snapshot("test_pool", "snap1")
    assert "Observer mode active" in str(exc_snap_del.value)

    with pytest.raises(PlatformCapabilityError) as exc_snap_res:
        adapter.restore_snapshot("test_pool", "snap1")
    assert "Observer mode active" in str(exc_snap_res.value)

    # Export & Import
    with pytest.raises(PlatformCapabilityError):
        adapter.export_pool("test_pool")

    with pytest.raises(PlatformCapabilityError):
        adapter.import_pool("test_pool")

    assert adapter.list_snapshots("test_pool") == []
    assert adapter.discover_external_pools() == []


# ============================================================================
# 3. Platform Detection Logic (Environment Overrides & Release Fingerprints)
# ============================================================================


def test_platform_detector_env_overrides():
    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "fygoos"}):
        assert StoragePlatformDetector.detect() == PlatformType.FYGOOS

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "zettos"}):
        assert StoragePlatformDetector.detect() == PlatformType.ZETTOS

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "ugos"}):
        assert StoragePlatformDetector.detect() == PlatformType.UGOS

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "generic_observer"}):
        assert StoragePlatformDetector.detect() == PlatformType.GENERIC_OBSERVER

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "observer"}):
        assert StoragePlatformDetector.detect() == PlatformType.GENERIC_OBSERVER

    with patch.dict(os.environ, {"ZETTNAS_PAL_MODE": "observer"}):
        # Clear ZETTNAS_PLATFORM and ZETTNAS_OBSERVER_ADAPTER so PAL_MODE is checked
        with patch.dict(os.environ, {"ZETTNAS_PLATFORM": "", "ZETTNAS_OBSERVER_ADAPTER": ""}):
            with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
                with patch("os.path.isfile", return_value=False):
                    assert StoragePlatformDetector.detect() == PlatformType.GENERIC_OBSERVER


def test_platform_detector_zettos_release_files():
    def mock_isfile(p):
        return p == "/etc/zettos-release"

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": ""}):
        with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", side_effect=mock_isfile):
                assert StoragePlatformDetector.detect() == PlatformType.ZETTOS


def test_platform_detector_fygoos_release_files():
    def mock_exists(p):
        return p == "/etc/fygoos-release"

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": ""}):
        with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with patch("os.path.exists", side_effect=mock_exists):
                    assert StoragePlatformDetector.detect() == PlatformType.FYGOOS


def test_platform_detector_ugos_release_files():
    def mock_exists(p):
        return p == "/etc/ugos-release"

    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": ""}):
        with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with patch("os.path.exists", side_effect=mock_exists):
                    assert StoragePlatformDetector.detect() == PlatformType.UGOS


def test_platform_detector_other_nas_release_files():
    # Synology DSM
    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": ""}):
        with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with patch("os.path.exists", side_effect=lambda p: p == "/etc/synoinfo.conf"):
                    assert StoragePlatformDetector.detect() == PlatformType.GENERIC_OBSERVER

    # QNAP QTS
    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": ""}):
        with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with patch("os.path.exists", side_effect=lambda p: p == "/etc/config/uLinux.conf"):
                    assert StoragePlatformDetector.detect() == PlatformType.GENERIC_OBSERVER

    # CasaOS
    with patch.dict(os.environ, {"ZETTNAS_PLATFORM": ""}):
        with patch("backend.hardware.pal.base._find_emhttp_dir", return_value=None):
            with patch("os.path.isfile", return_value=False):
                with patch("os.path.exists", side_effect=lambda p: p == "/etc/casaos"):
                    assert StoragePlatformDetector.detect() == PlatformType.GENERIC_OBSERVER


# ============================================================================
# 4. Factory Resolution (get_storage_platform)
# ============================================================================


def test_get_storage_platform_routing():
    with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.FYGOOS):
        assert isinstance(get_storage_platform(force_refresh=True), FygoOSStorageAdapter)

    with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.ZETTOS):
        assert isinstance(get_storage_platform(force_refresh=True), ZettOSStorageAdapter)

    with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.UGOS):
        assert isinstance(get_storage_platform(force_refresh=True), UgosStorageAdapter)

    with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.GENERIC_OBSERVER):
        assert isinstance(get_storage_platform(force_refresh=True), GenericObserverStorageAdapter)


# ============================================================================
# 5. UGOS mdstat, Pools & Telemetry
# ============================================================================


MOCK_MDSTAT_ACTIVE_RAID5 = """Personalities : [raid1] [raid6] [raid5] [raid4]
md1 : active raid5 sda3[0] sdd3[3] sdc3[2] sdb3[1]
      5860531200 blocks super 1.2 level 5, 512k chunk, algorithm 2 [4/4] [UUUU]

md0 : active raid1 sda1[0] sdb1[1]
      2097088 blocks super 1.2 [2/2] [UU]

unused devices: <none>
"""

MOCK_MDSTAT_RESYNCING = """Personalities : [raid1] [raid6] [raid5] [raid4]
md1 : active raid5 sda3[0] sdd3[3] sdc3[2] sdb3[1]
      5860531200 blocks super 1.2 level 5, 512k chunk, algorithm 2 [4/4] [UUUU]
      [===>.................]  resync = 18.2% (356000/1953510400) finish=120.5min speed=54321K/sec

unused devices: <none>
"""


def test_ugos_mdstat_parsing():
    adapter = UgosStorageAdapter()
    with patch("builtins.open", mock_open(read_data=MOCK_MDSTAT_ACTIVE_RAID5)):
        with patch("os.path.isfile", return_value=True):
            parsed = adapter._parse_mdstat()
            assert "md1" in parsed
            assert parsed["md1"]["level"] == "raid5"
            assert parsed["md1"]["state"] == "active"
            assert parsed["md1"]["degraded"] is False
            assert "sda3" in parsed["md1"]["members"]
            assert "sdb3" in parsed["md1"]["members"]
            assert parsed["md1"]["sync_action"] is None


def test_ugos_is_storage_busy_and_scrub():
    adapter = UgosStorageAdapter()
    # Idle
    with patch("builtins.open", mock_open(read_data=MOCK_MDSTAT_ACTIVE_RAID5)):
        with patch("os.path.isfile", return_value=True):
            assert adapter.is_storage_busy() is False

    # Resync active
    with patch("builtins.open", mock_open(read_data=MOCK_MDSTAT_RESYNCING)):
        with patch("os.path.isfile", return_value=True):
            assert adapter.is_storage_busy() is True
            scrub_res = adapter.trigger_scrub("volume1", action="status")
            assert scrub_res["platform"] == "ugos"
            assert scrub_res["status"] == "active"
            assert scrub_res["sync_action"] == "resync"
            assert scrub_res["progress_pct"] == 18.2


def test_ugos_list_pools_with_mdadm():
    adapter = UgosStorageAdapter(pool_path="/volume1")
    with (
        patch.object(
            adapter,
            "_parse_mdstat",
            return_value={
                "md1": {
                    "device": "md1",
                    "state": "active",
                    "level": "raid5",
                    "members": ["sda3", "sdb3", "sdc3"],
                    "degraded": False,
                    "sync_action": None,
                    "progress_pct": 0.0,
                }
            },
        ),
        patch.object(
            adapter,
            "_parse_mounts",
            return_value=[{"device": "/dev/md1", "mountpoint": "/volume1", "fstype": "btrfs", "options": "rw"}],
        ),
        patch("os.path.exists", return_value=True),
        patch("shutil.disk_usage", return_value=MagicMock(total=10000000000, used=4000000000, free=6000000000)),
    ):
        pools = adapter.list_pools()
        assert len(pools) >= 1
        vol1 = next((p for p in pools if "volume1" in p.id), None)
        assert vol1 is not None
        assert vol1.fs_type == "btrfs"
        assert vol1.fs_profile == "raid5"
        assert vol1.parity_protected is True
        assert vol1.status == "HEALTHY"


# ============================================================================
# 6. ZettOS Hybrid Storage & Scrub Telemetry
# ============================================================================


def test_zettos_scrub_zpool_and_btrfs():
    adapter = ZettOSStorageAdapter(pool_path="/mnt/storage")

    # ZFS Scrub start
    with patch.object(adapter, "_run_cmd", return_value=(0, "scrub started", "")):
        res = adapter.trigger_scrub("zfs:tank", action="start")
        assert res["platform"] == "zettos"
        assert res["status"] == "started"

    # ZFS Scrub status
    with patch.object(adapter, "_run_cmd", return_value=(0, "scrub in progress: 45%", "")):
        res = adapter.trigger_scrub("tank", action="status")
        assert res["status"] == "active"

    # Btrfs Scrub status
    with patch.object(adapter, "_run_cmd", return_value=(0, "scrub status for /mnt/storage: running", "")):
        res = adapter.trigger_scrub("btrfs_pool", action="status")
        assert res["status"] == "active"


# ============================================================================
# 7. Storage Engine Labeling in Read Storage
# ============================================================================


def test_storage_engine_labels():
    from backend.hardware.storage import read_storage

    with patch("shutil.disk_usage", return_value=MagicMock(total=1000000000, used=500000000, free=500000000)):
        with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.FYGOOS):
            data = read_storage()
            assert data["engine"] == "FygoOS Storage Engine"

        with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.ZETTOS):
            data = read_storage()
            assert data["engine"] == "ZettOS (ZFS / Btrfs Hybrid)"

        with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.UGOS):
            data = read_storage()
            assert data["engine"] == "UGOS (mdadm / LVM / Btrfs)"

        with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.GENERIC_OBSERVER):
            data = read_storage()
            assert data["engine"] == "Observer Telemetry Engine"


# ============================================================================
# 8. API Integration & Observer Rejections
# ============================================================================


def test_storage_api_with_observer_adapter(client, auth_headers):
    # Test that storage endpoints reflect observer mode
    with patch("backend.api.storage.get_storage_platform") as mock_get_pal:
        adapter = FygoOSStorageAdapter()
        mock_get_pal.return_value = adapter

        # GET /api/storage/platform
        resp = client.get("/api/storage/platform", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "fygoos"
        assert data["capabilities"]["is_observer_mode"] is True

        # POST /api/storage/pools rejected with 403
        pool_payload = {
            "name": "rogue_pool",
            "fs_type": "ext4",
            "profile": "single",
            "disks": ["/dev/sda"],
            "mountpoint": "/media/rogue",
        }
        res_create = client.post("/api/storage/pools", json=pool_payload, headers=auth_headers)
        assert res_create.status_code == 403
        assert "Forbidden in Observer Mode on fygoos" in res_create.json()["detail"]


def test_samba_api_with_observer_adapter(client, auth_headers):
    with patch("backend.api.samba.get_storage_platform") as mock_get_pal:
        adapter = UgosStorageAdapter()
        mock_get_pal.return_value = adapter

        share_payload = {
            "name": "illegal_share",
            "path": "/volume1/illegal",
            "comment": "forbidden",
            "public": True,
        }
        res = client.post("/api/samba/shares", json=share_payload, headers=auth_headers)
        assert res.status_code == 403
        assert "Observer Mode active" in res.json()["detail"]

        del_res = client.delete("/api/samba/shares/illegal_share", headers=auth_headers)
        assert del_res.status_code == 403
        assert "Observer Mode active" in del_res.json()["detail"]
