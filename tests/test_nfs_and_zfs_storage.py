"""
Unit and Integration Tests for NFS Engine, OpenZFS RAIDZ Provisioning,
and Storage Pool Renaming with Atomic Compatibility Symlinks.
"""

import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    PlatformCapabilityError,
    PlatformType,
    UnraidStorageAdapter,
    get_storage_platform,
)
from backend.main import app
from backend.services.nfs_engine import (
    NfsEngine,
    NfsExportRule,
    get_nfs_engine,
)


@pytest.fixture(autouse=True)
def isolated_nfs_and_storage_env(monkeypatch, tmp_path):
    """Isolates storage, samba, and nfs configs into temporary directories."""
    test_storage = tmp_path / "storage"
    test_storage.mkdir()
    test_data = tmp_path / "data"
    test_data.mkdir()
    test_nfs_exports_d = tmp_path / "exports.d" / "zettnas.exports"

    monkeypatch.setattr("backend.hardware.pal.base.POOL_PATH", str(test_storage))
    monkeypatch.setattr("backend.config.POOL_PATH", str(test_storage))
    monkeypatch.setattr("backend.config.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.nfs_engine.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.nfs_engine.NFS_DIR", str(test_data / "nfs"))
    monkeypatch.setattr("backend.services.nfs_engine.NFS_EXPORTS_FILE", str(test_data / "nfs" / "exports.json"))
    monkeypatch.setattr("backend.services.nfs_engine.ZETTNAS_EXPORTS_D_FILE", str(test_nfs_exports_d))
    monkeypatch.setattr("backend.services.samba_engine.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_DIR", str(test_data / "samba"))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_CONF_FILE", str(test_data / "samba" / "smb.conf"))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_SHARES_FILE", str(test_data / "samba" / "shares.json"))

    # Reset singletons
    monkeypatch.setattr("backend.hardware.pal_storage._CACHED_ADAPTER", None)
    monkeypatch.setattr("backend.services.nfs_engine._NFS_ENGINE_INSTANCE", None)
    monkeypatch.setattr("backend.services.samba_engine._SAMBA_ENGINE_INSTANCE", None)

    yield


# ==============================================================================
# 1. NFS Engine Tests
# ==============================================================================


def test_nfs_export_options_generation():
    engine = NfsEngine()

    # Rule 1: K8s PostgreSQL pod (no_root_squash, custom anonuid/gid, sync)
    rule1 = NfsExportRule(
        name="k8s_postgres",
        path="/mnt/storage/postgres",
        clients="10.244.0.0/16",
        permission="rw",
        squash="no_root_squash",
        anonuid=999,
        anongid=999,
        sync_mode="sync",
        no_subtree_check=True,
        insecure=True,
    )
    opts1 = engine.generate_export_options(rule1)
    assert "rw" in opts1
    assert "sync" in opts1
    assert "no_root_squash" in opts1
    assert "anonuid=999" in opts1
    assert "anongid=999" in opts1
    assert "no_subtree_check" in opts1
    assert "insecure" in opts1

    line1 = engine.generate_export_line(rule1)
    assert line1.startswith('"/mnt/storage/postgres" 10.244.0.0/16(')

    # Rule 2: Root squash with default anonymous mapping
    rule2 = NfsExportRule(
        name="public_backup",
        path="/mnt/storage/backup",
        clients="*",
        permission="ro",
        squash="root_squash",
        anonuid=1000,
        anongid=1000,
        sync_mode="async",
    )
    opts2 = engine.generate_export_options(rule2)
    assert "ro" in opts2
    assert "async" in opts2
    assert "root_squash" in opts2
    assert "anonuid=1000" in opts2


def test_nfs_engine_lifecycle(tmp_path):
    exports_d_file = str(tmp_path / "exports.d" / "zettnas.exports")
    engine = NfsEngine(exports_d_path=exports_d_file)

    rule = NfsExportRule(
        name="appdata",
        path="/mnt/storage/appdata",
        clients="*",
        permission="rw",
        squash="no_root_squash",
        anonuid=1000,
        anongid=1000,
    )
    engine.add_or_update_export(rule)

    assert len(engine.list_exports()) == 1
    retrieved = engine.get_export("appdata")
    assert retrieved is not None
    assert retrieved.squash == "no_root_squash"

    # Export file should be written
    assert os.path.isfile(exports_d_file)
    with open(exports_d_file) as f:
        content = f.read()
    assert '"/mnt/storage/appdata"' in content
    assert "no_root_squash" in content

    # Test remove
    removed = engine.remove_export("appdata")
    assert removed is True
    assert len(engine.list_exports()) == 0


# ==============================================================================
# 2. OpenZFS RAIDZ Provisioning & Validation Tests
# ==============================================================================


def test_openzfs_drive_count_validation():
    adapter = GenericLinuxStorageAdapter()

    # Empty disks rejected
    with pytest.raises(ValueError, match="At least one disk must be specified"):
        adapter.create_pool(name="zpool1", fs_type="zfs", profile="raidz1", disks=[], mountpoint="")

    # RAIDZ1 requires >= 3 disks
    with pytest.raises(ValueError, match="OpenZFS RAIDZ1 requires at least 3 disks"):
        adapter.create_pool(name="zpool1", fs_type="zfs", profile="raidz1", disks=["sda", "sdb"], mountpoint="")

    # RAIDZ2 requires >= 4 disks
    with pytest.raises(ValueError, match="OpenZFS RAIDZ2 requires at least 4 disks"):
        adapter.create_pool(name="zpool1", fs_type="zfs", profile="raidz2", disks=["sda", "sdb", "sdc"], mountpoint="")

    # RAIDZ3 requires >= 5 disks
    with pytest.raises(ValueError, match="OpenZFS RAIDZ3 requires at least 5 disks"):
        adapter.create_pool(
            name="zpool1", fs_type="zfs", profile="raidz3", disks=["sda", "sdb", "sdc", "sdd"], mountpoint=""
        )

    # Mirror requires >= 2 disks
    with pytest.raises(ValueError, match="OpenZFS Mirror requires at least 2 disks"):
        adapter.create_pool(name="zpool1", fs_type="zfs", profile="mirror", disks=["sda"], mountpoint="")


def test_openzfs_pool_creation_command():
    adapter = GenericLinuxStorageAdapter()
    recorded_commands = []

    def mock_run_cmd(cmd):
        recorded_commands.append(cmd)
        return (0, "", "")

    adapter._run_cmd = mock_run_cmd

    # Create RAIDZ2 pool with 4 disks
    res = adapter.create_pool(
        name="tank",
        fs_type="zfs",
        profile="raidz2",
        disks=["sda", "sdb", "sdc", "sdd"],
        mountpoint="/mnt/storage/tank",
    )

    assert res["status"] == "provisioned"
    assert res["name"] == "tank"
    assert res["fs_type"] == "zfs"
    assert res["profile"] == "raidz2"

    # Verify zpool command structure
    assert len(recorded_commands) >= 1
    zpool_cmd = recorded_commands[0]
    assert zpool_cmd[0] == "zpool"
    assert zpool_cmd[1] == "create"
    assert "-o" in zpool_cmd
    assert "ashift=12" in zpool_cmd
    assert "compression=zstd" in zpool_cmd
    assert "raidz2" in zpool_cmd
    assert "tank" in zpool_cmd


def test_openzfs_discovery_in_list_pools():
    adapter = GenericLinuxStorageAdapter()

    def mock_run_cmd(cmd):
        if cmd[:2] == ["zpool", "list"]:
            # Output: name\tsize\talloc\tfree\thealth
            return (0, "tank\t8000000000000\t2000000000000\t6000000000000\tONLINE", "")
        if cmd[:2] == ["zfs", "get"]:
            return (0, "/mnt/tank", "")
        if cmd[:2] == ["zpool", "status"]:
            return (0, "pool: tank\n state: ONLINE\n config:\n\t raidz2-0 ONLINE", "")
        return (0, "", "")

    adapter._run_cmd = mock_run_cmd

    pools = adapter.list_pools()
    # Should include default_pool + discovered ZFS pool
    zfs_pools = [p for p in pools if p.fs_type == "zfs"]
    assert len(zfs_pools) == 1
    zp = zfs_pools[0]
    assert zp.id == "tank"
    assert zp.fs_profile == "raidz2"
    assert zp.parity_protected is True
    assert zp.status == "HEALTHY"
    assert zp.mountpoint == "/mnt/tank"


# ==============================================================================
# 3. Storage Pool Renaming Tests
# ==============================================================================


def test_rename_pool_zfs(tmp_path):
    adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path))
    recorded_commands = []

    def mock_run_cmd(cmd):
        recorded_commands.append(cmd)
        if cmd[:2] == ["zpool", "status"]:
            return (0, "pool: oldtank\nstate: ONLINE", "")
        return (0, "", "")

    adapter._run_cmd = mock_run_cmd

    res = adapter.rename_pool("oldtank", "newtank")
    assert res["status"] == "renamed"
    assert res["old_name"] == "oldtank"
    assert res["new_name"] == "newtank"
    assert res["fs_type"] == "zfs"

    # Verify zpool export and import were called
    cmds_str = [" ".join(c) for c in recorded_commands]
    assert any("zpool export oldtank" in c for c in cmds_str)
    assert any("zpool import oldtank newtank" in c for c in cmds_str)


def test_rename_pool_empty_validation():
    adapter = GenericLinuxStorageAdapter()
    with pytest.raises(ValueError, match="New pool name cannot be empty"):
        adapter.rename_pool("mypool", "   ")


def test_unraid_observer_mode_rejections():
    adapter = UnraidStorageAdapter()

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.rename_pool("disk1", "newdisk")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.create_share(
            name="test",
            path="/mnt/user/test",
            export_nfs=True,
            nfs_squash="no_root_squash",
        )


# ==============================================================================
# 4. Storage API Endpoint Tests
# ==============================================================================


def test_api_create_share_with_nfs(client, auth_headers, monkeypatch, tmp_path):
    mock_adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "storage"))
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: mock_adapter)
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: mock_adapter)

    res = client.post(
        "/api/storage/shares",
        json={
            "name": "nfs_k8s_share",
            "path": str(tmp_path / "storage" / "nfs_k8s"),
            "comment": "K8s PVC Storage",
            "security": "public",
            "read_only": False,
            "export_smb": True,
            "export_nfs": True,
            "nfs_squash": "no_root_squash",
            "nfs_anonuid": 1000,
            "nfs_anongid": 1000,
            "nfs_sync": True,
            "nfs_clients": "10.0.0.0/8",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "created"
    assert data["name"] == "nfs_k8s_share"
    assert data["export_nfs"] is True

    # Verify NfsEngine registered rule
    nfs_eng = get_nfs_engine()
    rule = nfs_eng.get_export("nfs_k8s_share")
    assert rule is not None
    assert rule.squash == "no_root_squash"
    assert rule.clients == "10.0.0.0/8"


def test_api_rename_storage_pool(client, auth_headers, monkeypatch, tmp_path):
    mock_adapter = GenericLinuxStorageAdapter(pool_path=str(tmp_path / "pools"))
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: mock_adapter)
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: mock_adapter)
    monkeypatch.setattr(mock_adapter, "_run_cmd", lambda cmd: (0, "ok", ""))

    res = client.post(
        "/api/storage/pools/oldpool/rename",
        json={"new_name": "newpool"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "renamed"
    assert data["old_name"] == "oldpool"
    assert data["new_name"] == "newpool"
