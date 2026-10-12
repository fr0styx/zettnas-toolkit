"""
Unit and Integration Tests for Batch 3 Community Features:
1. External JBOD USB/TB Storage Pool Lifecycle (Export, Detach, Import, Discovery).
2. Canonical persistent /dev/disk/by-id/ resolution invariant.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    UnraidStorageAdapter,
    PlatformCapabilityError,
    PlatformType,
)


@pytest.fixture(autouse=True)
def isolated_storage_env(monkeypatch, tmp_path):
    test_storage = tmp_path / "storage"
    test_storage.mkdir()
    test_data = tmp_path / "data"
    test_data.mkdir()

    monkeypatch.setattr("backend.hardware.pal_storage.POOL_PATH", str(test_storage))
    monkeypatch.setattr("backend.config.POOL_PATH", str(test_storage))
    monkeypatch.setattr("backend.config.DATA_DIR", str(test_data))
    monkeypatch.setattr("backend.hardware.pal_storage._CACHED_ADAPTER", None)
    yield


# ==============================================================================
# 1. Canonical /dev/disk/by-id/ Resolution Invariant
# ==============================================================================


def test_resolve_disk_path_by_id_symlink(tmp_path, monkeypatch):
    """Verifies _resolve_disk_path prefers persistent /dev/disk/by-id identifiers."""
    adapter = GenericLinuxStorageAdapter()

    # Create mock /dev/disk/by-id directory
    by_id_dir = tmp_path / "dev" / "disk" / "by-id"
    by_id_dir.mkdir(parents=True)
    real_dev = tmp_path / "dev" / "sde"
    real_dev.touch()

    # Create symlinks: partition link (should be skipped), ata link, and wwn link (top priority)
    part_link = by_id_dir / "ata-WDC_WD40EFRX_123-part1"
    part_link.symlink_to(real_dev)
    ata_link = by_id_dir / "ata-WDC_WD40EFRX_123"
    ata_link.symlink_to(real_dev)
    wwn_link = by_id_dir / "wwn-0x5000cca234"
    wwn_link.symlink_to(real_dev)

    # Mock by_id directory searching
    monkeypatch.setattr("backend.hardware.pal_storage.HOST_DEV", str(tmp_path / "dev"))
    resolved = adapter._resolve_disk_path("sde")
    # Should resolve to top-ranked WWN identifier
    assert resolved == str(wwn_link)

    # Fallback when no by-id exists
    resolved_fallback = adapter._resolve_disk_path("sdz")
    assert resolved_fallback in ("/dev/sdz", f"{tmp_path}/dev/sdz")


# ==============================================================================
# 2. Pool Export & Safe Detachment Lifecycle
# ==============================================================================


def test_export_pool_zfs_success(monkeypatch, tmp_path):
    adapter = GenericLinuxStorageAdapter()
    recorded_cmds = []

    def mock_run_cmd(cmd):
        recorded_cmds.append(cmd)
        if cmd[:2] == ["zpool", "status"]:
            return 0, "pool: ext_backup_pool state: ONLINE", ""
        if cmd[:2] == ["zfs", "get"]:
            return 0, str(tmp_path / "ext_backup_pool"), ""
        if cmd[0] == "fuser":
            return 1, "", ""  # No active handles
        if cmd[0] in ("sync", "zpool"):
            return 0, "", ""
        return 0, "", ""

    adapter._run_cmd = mock_run_cmd

    res = adapter.export_pool("ext_backup_pool", force=False)
    assert res["status"] == "exported"
    assert res["pool_id"] == "ext_backup_pool"
    assert res["fs_type"] == "zfs"
    assert res["safe_to_disconnect"] is True
    assert any("sync" in c[0] for c in recorded_cmds)
    assert any("export" in c[1] for c in recorded_cmds if len(c) > 1 and c[0] == "zpool")


def test_export_pool_busy_without_force(monkeypatch, tmp_path):
    adapter = GenericLinuxStorageAdapter()
    mount_dir = tmp_path / "busy_pool"
    mount_dir.mkdir()

    def mock_run_cmd(cmd):
        if cmd[:2] == ["zpool", "status"]:
            return 1, "", "no such pool"
        if cmd[0] == "fuser":
            return 0, "1234 5678", ""  # 2 active process handles
        return 0, "", ""

    adapter._run_cmd = mock_run_cmd
    adapter._pool_path = str(tmp_path)

    # Without force: should raise RuntimeError
    with pytest.raises(RuntimeError, match="has 2 active process"):
        adapter.export_pool("busy_pool", force=False)

    # With force: should succeed
    res = adapter.export_pool("busy_pool", force=True)
    assert res["status"] == "exported"
    assert res["safe_to_disconnect"] is True


def test_unraid_export_pool_guardrails():
    adapter = UnraidStorageAdapter()

    # Primary unraid_array or default_pool is protected
    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.export_pool("unraid_array")

    with pytest.raises(PlatformCapabilityError, match="Observer mode active"):
        adapter.export_pool("default_pool")

    # External detached ZFS pool can be exported
    def mock_run_cmd(cmd):
        if cmd[:2] == ["zpool", "status"]:
            return 0, "ONLINE", ""
        return 0, "", ""

    adapter._run_cmd = mock_run_cmd
    res = adapter.export_pool("usb_das_pool", force=False)
    assert res["status"] == "exported"
    assert res["safe_to_disconnect"] is True


# ==============================================================================
# 3. External Pool Discovery & Import
# ==============================================================================


def test_discover_external_pools_parsing():
    adapter = GenericLinuxStorageAdapter()
    sample_zpool_import = """
   pool: ext_das_vault
     id: 178239019283019283
  state: ONLINE
 action: The pool can be imported using its name or numeric identifier.
 config:

    ext_das_vault  ONLINE
      sda          ONLINE
      sdb          ONLINE

   pool: backup_offsite
     id: 998877665544332211
  state: ONLINE
 action: The pool can be imported using its name or numeric identifier.
 config:

    backup_offsite ONLINE
      sdc          ONLINE
"""
    adapter._run_cmd = lambda cmd: (0, sample_zpool_import, "") if cmd == ["zpool", "import"] else (1, "", "")

    discovered = adapter.discover_external_pools()
    assert len(discovered) == 2
    assert discovered[0]["pool_id"] == "ext_das_vault"
    assert discovered[0]["fs_type"] == "zfs"
    assert discovered[0]["status"] == "ONLINE"
    assert discovered[1]["pool_id"] == "backup_offsite"


def test_import_pool_zfs():
    adapter = GenericLinuxStorageAdapter()
    recorded_cmds = []

    def mock_run_cmd(cmd):
        recorded_cmds.append(cmd)
        return 0, "", ""

    adapter._run_cmd = mock_run_cmd
    res = adapter.import_pool("ext_das_vault", fs_type="zfs")
    assert res["status"] == "imported"
    assert res["pool_id"] == "ext_das_vault"
    assert recorded_cmds[0] == ["zpool", "import", "-f", "ext_das_vault"]


# ==============================================================================
# 4. REST API Endpoint Integration Tests
# ==============================================================================


def test_storage_api_export_and_discover(client, auth_headers):
    mock_platform = MagicMock()
    mock_platform.discover_external_pools.return_value = [{"pool_id": "ext_pool", "fs_type": "zfs", "status": "ONLINE"}]
    mock_platform.export_pool.return_value = {"status": "exported", "safe_to_disconnect": True}
    mock_platform.import_pool.return_value = {"status": "imported", "pool_id": "ext_pool"}

    with patch("backend.api.storage.get_storage_platform", return_value=mock_platform):
        # 1. Discover external pools
        res = client.get("/api/storage/pools/discover", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()["discovered_pools"]) == 1
        assert res.json()["discovered_pools"][0]["pool_id"] == "ext_pool"

        # 2. Export pool endpoint
        exp_res = client.post("/api/storage/pools/ext_pool/export", json={"force": False}, headers=auth_headers)
        assert exp_res.status_code == 200
        assert exp_res.json()["safe_to_disconnect"] is True

        # 3. Import pool endpoint
        imp_res = client.post(
            "/api/storage/pools/import", json={"pool_id": "ext_pool", "fs_type": "zfs"}, headers=auth_headers
        )
        assert imp_res.status_code == 200
        assert imp_res.json()["status"] == "imported"
