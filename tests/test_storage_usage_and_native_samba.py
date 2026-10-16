"""
Tests for Universal Storage Pool Usage Resolution & Turnkey OS Native Samba Abstraction.
Validates:
1. Superblock parsing for Ext4 (32-bit & 64-bit), XFS, and Btrfs on block devices.
2. CasaOS / ZettOS SQLite local-storage.db inspection for pool statistics.
3. Accurate used_bytes, free_bytes, and used_pct calculations on MDRAID arrays.
4. Native Samba detection, sidecar disable policy, and troubled container suppression on turnkey OSes.
"""

import os
import sqlite3
import struct
from unittest.mock import MagicMock, patch
import pytest

from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    PlatformType,
    StoragePlatformDetector,
    ZettOSStorageAdapter,
)
from backend.services.samba_engine import SambaEngine, SambaStatus, get_samba_engine
from backend.services.docker_diagnostics import collect_docker_diagnostics


def test_ext4_superblock_parser_32bit(tmp_path):
    """Verifies that _parse_fs_superblock accurately extracts Ext4 32-bit parameters."""
    dev_file = tmp_path / "mock_ext4_dev"
    with open(dev_file, "wb") as f:
        f.seek(1024 + 1024)
        f.write(b"\x00")

    # Build valid Ext4 superblock at offset 1024
    sb = bytearray(1024)
    # s_blocks_count_lo at 0x04: 10,000,000 blocks
    struct.pack_into("<I", sb, 0x04, 10_000_000)
    # s_free_blocks_count_lo at 0x0C: 2,000,000 blocks
    struct.pack_into("<I", sb, 0x0C, 2_000_000)
    # s_log_block_size at 0x18: 2 (1024 << 2 = 4096 bytes)
    struct.pack_into("<I", sb, 0x18, 2)
    # s_magic at 0x38: 0xEF53
    struct.pack_into("<H", sb, 0x38, 0xEF53)

    with open(dev_file, "r+b") as f:
        f.seek(1024)
        f.write(sb)

    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")
    res = adapter._parse_fs_superblock(str(dev_file))

    assert res is not None
    assert res["fstype"] == "ext4"
    assert res["total_bytes"] == 10_000_000 * 4096
    assert res["free_bytes"] == 2_000_000 * 4096
    assert res["used_bytes"] == 8_000_000 * 4096
    assert res["used_pct"] == 80.0


def test_ext4_superblock_parser_64bit_large_array(tmp_path):
    """Verifies that _parse_fs_superblock accurately extracts Ext4 64-bit parameters for multi-terabyte arrays."""
    dev_file = tmp_path / "mock_ext4_64bit_dev"
    with open(dev_file, "wb") as f:
        f.seek(1024 + 1024)
        f.write(b"\x00")

    # 43.36 TB array = ~11,639,406,592 blocks of 4096 bytes
    # total_blocks = 11,639,406,592 = (2 << 32) + 3,049,473,536
    # free_blocks = 11,421,000,000 = (2 << 32) + 2,831,066,944
    total_blocks = 11_639_406_592
    free_blocks = 11_421_000_000
    used_blocks = total_blocks - free_blocks

    sb = bytearray(1024)
    struct.pack_into("<I", sb, 0x04, total_blocks & 0xFFFFFFFF)
    struct.pack_into("<I", sb, 0x0C, free_blocks & 0xFFFFFFFF)
    struct.pack_into("<I", sb, 0x18, 2)  # 4096 byte block size
    struct.pack_into("<H", sb, 0x38, 0xEF53)  # magic
    struct.pack_into("<I", sb, 0x60, 0x80)  # EXT4_FEATURE_INCOMPAT_64BIT
    struct.pack_into("<I", sb, 0x150, total_blocks >> 32)
    struct.pack_into("<I", sb, 0x158, free_blocks >> 32)

    with open(dev_file, "r+b") as f:
        f.seek(1024)
        f.write(sb)

    adapter = ZettOSStorageAdapter(pool_path="/mnt/storage")
    res = adapter._parse_fs_superblock(str(dev_file))

    assert res is not None
    assert res["fstype"] == "ext4"
    assert res["total_bytes"] == total_blocks * 4096
    assert res["free_bytes"] == free_blocks * 4096
    assert res["used_bytes"] == used_blocks * 4096
    assert round(res["used_bytes"] / (1024**3), 2) == 833.16  # ~833 GB used!


def test_xfs_superblock_parser(tmp_path):
    """Verifies that _parse_fs_superblock accurately extracts XFS parameters."""
    dev_file = tmp_path / "mock_xfs_dev"
    with open(dev_file, "wb") as f:
        f.seek(256)
        f.write(b"\x00")

    sb = bytearray(256)
    sb[0:4] = b"XFSB"
    struct.pack_into(">I", sb, 0x04, 4096)  # bsize
    struct.pack_into(">Q", sb, 0x08, 1_000_000_000)  # dblocks (4 TB)
    struct.pack_into(">Q", sb, 0x90, 750_000_000)  # fdblocks (3 TB free)

    with open(dev_file, "r+b") as f:
        f.seek(0)
        f.write(sb)

    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")
    res = adapter._parse_fs_superblock(str(dev_file))

    assert res is not None
    assert res["fstype"] == "xfs"
    assert res["total_bytes"] == 4_096_000_000_000
    assert res["free_bytes"] == 3_072_000_000_000
    assert res["used_bytes"] == 1_024_000_000_000
    assert res["used_pct"] == 25.0


def test_btrfs_superblock_parser(tmp_path):
    """Verifies that _parse_fs_superblock accurately extracts Btrfs parameters."""
    dev_file = tmp_path / "mock_btrfs_dev"
    with open(dev_file, "wb") as f:
        f.seek(0x10000 + 512)
        f.write(b"\x00")

    sb = bytearray(512)
    sb[0x40:0x48] = b"_BHRfS_M"
    struct.pack_into("<Q", sb, 0x70, 4_000_000_000_000)  # total_bytes (4 TB)
    struct.pack_into("<Q", sb, 0x78, 1_300_000_000_000)  # bytes_used (1.3 TB)

    with open(dev_file, "r+b") as f:
        f.seek(0x10000)
        f.write(sb)

    adapter = ZettOSStorageAdapter(pool_path="/mnt/storage")
    res = adapter._parse_fs_superblock(str(dev_file))

    assert res is not None
    assert res["fstype"] == "btrfs"
    assert res["total_bytes"] == 4_000_000_000_000
    assert res["used_bytes"] == 1_300_000_000_000
    assert res["free_bytes"] == 2_700_000_000_000
    assert res["used_pct"] == 32.5


def test_casaos_local_storage_db_reader(tmp_path, monkeypatch):
    """Verifies that _read_casaos_storage_db extracts pool metadata from SQLite."""
    db_file = tmp_path / "local-storage.db"
    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE raids (
            id INTEGER PRIMARY KEY,
            name TEXT,
            path TEXT,
            mount_point TEXT,
            size INTEGER,
            used INTEGER,
            free INTEGER,
            fs_type TEXT
        );
    """)
    cursor.execute("""
        INSERT INTO raids (name, path, mount_point, size, used, free, fs_type)
        VALUES ('Pool_2', '/dev/md3', '/media/Pool_2', 47683726745600, 874288000000, 46809438745600, 'ext4');
    """)
    conn.commit()
    conn.close()

    adapter = ZettOSStorageAdapter(pool_path="/mnt/storage")
    orig_connect = sqlite3.connect
    with patch(
        "os.path.isfile",
        side_effect=lambda p: str(p) == str(db_file) or str(p) == "/var/lib/casaos/db/local-storage.db",
    ):
        with patch(
            "backend.hardware.pal_storage.sqlite3.connect", side_effect=lambda *args, **kw: orig_connect(str(db_file))
        ):
            records = adapter._read_casaos_storage_db()
            assert "md3" in records
            assert records["md3"]["name"] == "Pool_2"
            assert records["md3"]["used"] == 874288000000


def test_mdraid_used_space_resolution_in_zettos_adapter():
    """Verifies that ZettOSStorageAdapter populates real used_bytes on md3 RAID5 even when mount is external."""
    adapter = ZettOSStorageAdapter(pool_path="/mnt/storage")

    mock_mdstat = {
        "md3": {
            "device": "md3",
            "state": "active",
            "level": "raid5",
            "members": ["sdc", "sdd", "sde", "sdf"],
            "blocks": 46562663424,
            "size_bytes": 47683726745600,
            "degraded": False,
        }
    }
    mock_mounts = [
        {"device": "/dev/md3", "mountpoint": "/media/Pool_2", "fstype": "ext4", "options": "rw"},
    ]

    mock_db_records = {
        "md3": {
            "name": "Pool_2",
            "size": 47683726745600,
            "used": 874288000000,  # ~814 GB used
            "free": 46809438745600,
            "fs_type": "ext4",
        }
    }

    with patch.object(adapter, "_parse_mdstat", return_value=mock_mdstat):
        with patch.object(adapter, "_parse_mounts", return_value=mock_mounts):
            with patch.object(adapter, "_discover_hal_disks", return_value=[]):
                with patch.object(adapter, "_read_casaos_storage_db", return_value=mock_db_records):
                    with patch("shutil.disk_usage", side_effect=FileNotFoundError("Not mounted in container")):
                        pools = adapter.list_pools()
                        md3_pool = next(p for p in pools if p.id == "md3")
                        assert md3_pool.used_bytes == 874288000000
                        assert md3_pool.free_bytes == 46809438745600
                        assert md3_pool.used_pct == 1.8
                        assert md3_pool.fs_type == "ext4"


def test_turnkey_native_samba_detection_and_sidecar_policy(tmp_path, monkeypatch):
    """Verifies that on ZettOS / Turnkey OS, native Samba is detected, disable_sidecar marker is generated, and mode is host_native."""
    test_samba_dir = tmp_path / "samba"
    test_samba_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_DIR", str(test_samba_dir))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_CONF_FILE", str(test_samba_dir / "smb.conf"))
    monkeypatch.setattr("backend.services.samba_engine.SAMBA_SHARES_FILE", str(test_samba_dir / "shares.json"))
    monkeypatch.setattr("backend.services.samba_engine._SAMBA_ENGINE_INSTANCE", None)

    with patch("backend.hardware.pal_storage.StoragePlatformDetector.detect", return_value=PlatformType.ZETTOS):
        engine = SambaEngine()
        status = engine.get_status()

        assert status.mode == "host_native"
        assert status.native_samba_active is True
        assert os.path.isfile(str(test_samba_dir / "disable_sidecar"))

        # Verify sidecar readiness returns False
        can_run, reason = engine.can_run_sidecar()
        assert can_run is False
        assert "zettos" in reason.lower()


def test_troubled_containers_suppresses_zettnas_samba_on_turnkey_os():
    """Verifies that docker diagnostics does not report zettnas-samba as troubled container on Turnkey OS."""
    mock_containers = [
        {
            "Id": "abc123samba",
            "Names": ["/zettnas-samba"],
            "State": "restarting",
            "Status": "Restarting (1) 5 seconds ago",
        },
        {
            "Id": "def456crashed",
            "Names": ["/crashed-app"],
            "State": "dead",
            "Status": "Dead",
        },
    ]

    with patch("backend.services.docker_diagnostics._docker_api_get") as mock_get:

        def side_effect(endpoint, **kwargs):
            if endpoint == "/info":
                return {"ServerVersion": "24.0.5"}
            if endpoint == "/system/df":
                return {}
            if endpoint == "/containers/json?all=1":
                return mock_containers
            if "/json" in endpoint:
                return {"State": {"ExitCode": 1, "Error": "port already in use"}}
            return None

        mock_get.side_effect = side_effect
        with patch("backend.hardware.pal_storage.StoragePlatformDetector.detect", return_value=PlatformType.ZETTOS):
            diag = collect_docker_diagnostics()
            assert diag["daemon_connected"] is True
            # crashed-app should be in troubled containers, but zettnas-samba should be suppressed
            troubled_names = [c["name"] for c in diag.get("troubled_containers", []) if isinstance(c, dict)]
            assert "crashed-app" in troubled_names
            assert "zettnas-samba" not in troubled_names
