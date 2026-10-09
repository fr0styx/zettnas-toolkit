"""
Unit and Integration Tests for Sprint 5:
Generic Linux Storage Adapter, Btrfs RAID Pools, Subvolume Snapshots,
and Samba Engine with macOS Time Machine (vfs_fruit) support.
"""

import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    UnraidStorageAdapter,
    PlatformCapabilities,
    PlatformCapabilityError,
    PlatformType,
    get_storage_platform,
)
from backend.services.samba_engine import (
    SambaEngine,
    SambaShareConfig,
    get_samba_engine,
)


@pytest.fixture(autouse=True)
def isolated_storage_env(monkeypatch, tmp_path):
    """Isolates storage and samba configs into a temporary directory."""
    test_storage = tmp_path / "storage"
    test_storage.mkdir()
    test_data = tmp_path / "data"
    test_data.mkdir()

    monkeypatch.setattr("backend.hardware.pal_storage.POOL_PATH", str(test_storage))
    monkeypatch.setattr("backend.config.POOL_PATH", str(test_storage))
    monkeypatch.setattr("backend.config.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.samba_engine.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_DIR", str(test_data / "samba"))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_CONF_FILE", str(test_data / "samba" / "smb.conf"))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_SHARES_FILE", str(test_data / "samba" / "shares.json"))

    # Reset singletons
    monkeypatch.setattr("backend.hardware.pal_storage._CACHED_ADAPTER", None)
    monkeypatch.setattr("backend.services.samba_engine._SAMBA_ENGINE_INSTANCE", None)

    yield


# ==============================================================================
# 1. GenericLinuxStorageAdapter Unit Tests
# ==============================================================================


def test_generic_linux_capabilities():
    adapter = GenericLinuxStorageAdapter()
    caps = adapter.get_capabilities()
    assert caps.platform == PlatformType.GENERIC_LINUX
    assert caps.is_observer_mode is False
    assert caps.can_create_pools is True
    assert caps.can_destroy_pools is True
    assert caps.can_manage_shares is True
    assert caps.can_trigger_scrub is True
    assert "btrfs" in caps.supported_filesystems


def test_btrfs_pool_creation_validation():
    adapter = GenericLinuxStorageAdapter()

    # Empty disks rejected
    with pytest.raises(ValueError, match="At least one disk must be specified"):
        adapter.create_pool(name="test", fs_type="btrfs", profile="raid1", disks=[], mountpoint="")

    # RAID1 requires >= 2 disks
    with pytest.raises(ValueError, match="RAID1 requires at least 2 disks"):
        adapter.create_pool(name="test", fs_type="btrfs", profile="raid1", disks=["sda"], mountpoint="")

    # RAID10 requires >= 4 disks
    with pytest.raises(ValueError, match="RAID10 requires at least 4 disks"):
        adapter.create_pool(name="test", fs_type="btrfs", profile="raid10", disks=["sda", "sdb"], mountpoint="")


def test_btrfs_pool_creation_and_destruction(monkeypatch, tmp_path):
    adapter = GenericLinuxStorageAdapter()
    adapter._pool_path = str(tmp_path / "pool_mount")

    recorded_cmds = []

    def mock_run_cmd(cmd):
        recorded_cmds.append(cmd)
        return 0, "mock success", ""

    monkeypatch.setattr(adapter, "_run_cmd", mock_run_cmd)

    res = adapter.create_pool(
        name="vault",
        fs_type="btrfs",
        profile="raid1",
        disks=["sdb", "sdc"],
        mountpoint=str(tmp_path / "pool_mount"),
    )

    assert res["status"] == "provisioned"
    assert res["name"] == "vault"
    assert res["profile"] == "raid1"
    assert len(recorded_cmds) >= 4  # mkfs, mount, subvolume @shares, subvolume @snapshots

    # Destroy pool
    destroy_res = adapter.destroy_pool("vault")
    assert destroy_res["status"] == "destroyed"
    assert any("umount" in cmd[0] for cmd in recorded_cmds)


def test_btrfs_scrub_lifecycle(monkeypatch):
    adapter = GenericLinuxStorageAdapter()

    # Mock scrub start
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (0, "scrub started", ""))
    start_res = adapter.trigger_scrub("vault", action="start")
    assert start_res["status"] == "started"

    # Mock scrub cancel
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (0, "scrub cancelled", ""))
    cancel_res = adapter.trigger_scrub("vault", action="cancel")
    assert cancel_res["status"] == "cancelled"

    # Mock scrub status
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (0, "scrub status: 0 errors", ""))
    status_res = adapter.trigger_scrub("vault", action="status")
    assert status_res["status"] == "active"


def test_btrfs_snapshots_lifecycle(monkeypatch, tmp_path):
    adapter = GenericLinuxStorageAdapter()
    adapter._pool_path = str(tmp_path)

    # 1. Create snapshot
    recorded_cmds = []
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (recorded_cmds.append(cmd) or 0, "ok", ""))

    snap_res = adapter.create_snapshot("default_pool", "@shares", "snap-2026-10-09", readonly=True)
    assert snap_res["status"] == "created"
    assert snap_res["readonly"] is True
    assert any("snapshot" in cmd for cmd in recorded_cmds)

    # 2. List snapshots
    snaps_dir = tmp_path / "@snapshots"
    snaps_dir.mkdir(parents=True, exist_ok=True)
    (snaps_dir / "snap-2026-10-09").mkdir()

    snaps = adapter.list_snapshots("default_pool")
    assert len(snaps) == 1
    assert snaps[0]["name"] == "snap-2026-10-09"

    # 3. Delete snapshot
    del_res = adapter.delete_snapshot("default_pool", "snap-2026-10-09")
    assert del_res["status"] == "deleted"


# ==============================================================================
# 2. UnraidStorageAdapter Observer Mode Enforcement Tests
# ==============================================================================


def test_unraid_observer_mode_rejections():
    adapter = UnraidStorageAdapter()

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.create_pool("test", "btrfs", "raid1", ["sdb", "sdc"], "/mnt/user")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.destroy_pool("unraid_array")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.create_share("test", "/mnt/user/test")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.delete_share("test")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.create_snapshot("unraid_array", "@shares", "snap-1")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.delete_snapshot("unraid_array", "snap-1")


# ==============================================================================
# 3. SambaEngine & Apple Time Machine (vfs_fruit) Tests
# ==============================================================================


def test_samba_engine_conf_generation_and_timemachine(tmp_path):
    engine = SambaEngine()

    # Add standard share
    share1 = SambaShareConfig(
        name="vault",
        path=str(tmp_path / "vault"),
        comment="Secure Vault",
        read_only=False,
        guest_ok=True,
    )
    engine.add_or_update_share(share1)

    # Add Time Machine share
    tm_share = SambaShareConfig(
        name="TimeMachine",
        path=str(tmp_path / "tm"),
        comment="Mac Backup",
        read_only=False,
        guest_ok=False,
        timemachine=True,
        timemachine_quota_gb=500,
    )
    engine.add_or_update_share(tm_share)

    conf_text = engine.get_config_text()

    # Verify macOS vfs_fruit global options
    assert "vfs objects = catia fruit streams_xattr" in conf_text
    assert "fruit:metadata = netatalk" in conf_text
    assert "fruit:model = MacPro" in conf_text
    assert "min protocol = SMB2_10" in conf_text

    # Verify standard share
    assert "[vault]" in conf_text
    assert "read only = no" in conf_text
    assert "guest ok = yes" in conf_text

    # Verify Time Machine share
    assert "[TimeMachine]" in conf_text
    assert "fruit:time machine = yes" in conf_text
    assert "fruit:time machine max size = 500G" in conf_text

    # Remove share
    assert engine.remove_share("vault") is True
    assert "[vault]" not in engine.get_config_text()
    assert "[TimeMachine]" in engine.get_config_text()


# ==============================================================================
# 4. REST API Endpoint Integration Tests
# ==============================================================================


def test_api_storage_platform_info(client, auth_headers):
    res = client.get("/api/storage/platform", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "platform" in data
    assert "capabilities" in data


def test_api_samba_endpoints(client, auth_headers, monkeypatch):
    # Mock platform as generic linux for share mutation
    monkeypatch.setattr(
        "backend.hardware.pal_storage.StoragePlatformDetector.detect",
        lambda: PlatformType.GENERIC_LINUX,
    )

    # Status
    res = client.get("/api/samba/status", headers=auth_headers)
    assert res.status_code == 200
    assert "shares_count" in res.json()

    # List shares
    res = client.get("/api/samba/shares", headers=auth_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)

    # Config
    res = client.get("/api/samba/config", headers=auth_headers)
    assert res.status_code == 200
    assert "fruit:model = MacPro" in res.text

    # Create share
    payload = {
        "name": "apishare",
        "path": "/mnt/storage/apishare",
        "comment": "API Test Share",
        "read_only": False,
        "guest_ok": True,
        "browseable": True,
        "timemachine": True,
        "timemachine_quota_gb": 250,
        "force_user": "root",
        "force_group": "root",
    }
    create_res = client.post("/api/samba/shares", json=payload, headers=auth_headers)
    assert create_res.status_code == 200
    assert create_res.json()["name"] == "apishare"

    # Delete share
    del_res = client.delete("/api/samba/shares/apishare", headers=auth_headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"


def test_api_pool_snapshots_and_lifecycle(client, auth_headers, monkeypatch, tmp_path):
    # Mock adapter as GenericLinuxStorageAdapter
    generic_adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "pools"))
    monkeypatch.setattr(
        "backend.api.storage.get_storage_platform",
        lambda: generic_adapter,
    )
    monkeypatch.setattr(
        generic_adapter,
        "_run_cmd",
        lambda cmd: (0, "ok", ""),
    )

    # Create pool via API
    mount_dir = str(tmp_path / "datapool")
    pool_payload = {
        "name": "datapool",
        "fs_type": "btrfs",
        "profile": "raid1",
        "disks": ["sdb", "sdc"],
        "mountpoint": mount_dir,
    }
    create_pool_res = client.post("/api/storage/pools", json=pool_payload, headers=auth_headers)
    assert create_pool_res.status_code == 200
    assert create_pool_res.json()["name"] == "datapool"

    # Take snapshot via API
    snap_payload = {
        "subvolume": "@shares",
        "snapshot_name": "snap-unit-test",
        "readonly": True,
    }
    snap_res = client.post("/api/storage/pools/datapool/snapshots", json=snap_payload, headers=auth_headers)
    assert snap_res.status_code == 200
    assert snap_res.json()["status"] == "created"

    # Delete pool via API
    del_pool_res = client.delete("/api/storage/pools/datapool", headers=auth_headers)
    assert del_pool_res.status_code == 200
    assert del_pool_res.json()["status"] == "destroyed"
