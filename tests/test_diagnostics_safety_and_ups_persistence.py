"""Tests for hardware MMIO safety guards (D4 bus abort / reboot prevention)
and multi-tier UPS configuration persistence and auto-recovery.
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

from backend.db import get_app_config_value, init_db, set_app_config_value
from backend.hardware.fans import (
    ZettlabMmioFanController,
    get_detailed_fan_telemetry,
    is_zettlab_mmio_supported,
)
from backend.hardware.ups import (
    _detect_host_nut_config,
    _query_nut_socket,
    load_ups_config,
    save_ups_config,
)


def setup_function():
    init_db()


# ==============================================================================
# 1. MMIO Hardware Safety & D4 Reboot Prevention Tests
# ==============================================================================


def test_is_zettlab_mmio_supported_rejects_non_x86():
    with patch("platform.machine", return_value="aarch64"):
        assert is_zettlab_mmio_supported() is False

    with patch("platform.machine", return_value="armv7l"):
        assert is_zettlab_mmio_supported() is False


def test_is_zettlab_mmio_supported_rejects_d4():
    with (
        patch("platform.machine", return_value="x86_64"),
        patch("backend.hardware.storage.detect_chassis_model", return_value="d4"),
        patch("backend.hardware.unraid.read_unraid_status", return_value={"available": True, "model": "Zettlab D4"}),
    ):
        assert is_zettlab_mmio_supported() is False


def test_is_zettlab_mmio_supported_allows_d8u():
    with (
        patch("platform.machine", return_value="x86_64"),
        patch("backend.hardware.storage.detect_chassis_model", return_value="d8u"),
    ):
        assert is_zettlab_mmio_supported() is True


def test_is_zettlab_mmio_supported_honors_env_overrides():
    with (
        patch.dict(os.environ, {"FORCE_ZETTLAB_MMIO": "0"}),
        patch("platform.machine", return_value="x86_64"),
        patch("backend.hardware.storage.detect_chassis_model", return_value="d8u"),
    ):
        assert is_zettlab_mmio_supported() is False

    with patch.dict(os.environ, {"FORCE_ZETTLAB_MMIO": "1"}):
        assert is_zettlab_mmio_supported() is True


def test_mmio_controller_does_not_open_dev_mem_when_unsupported():
    ctrl = ZettlabMmioFanController()
    with (
        patch("backend.hardware.fans.is_zettlab_mmio_supported", return_value=False),
        patch("os.open") as mock_open,
    ):
        assert ctrl.is_available() is False
        assert ctrl._ensure_mapped() is False
        mock_open.assert_not_called()


def test_detailed_fan_telemetry_respects_mmio_support_flag():
    with (
        patch("backend.hardware.fans.is_zettlab_mmio_supported", return_value=False),
        patch("backend.hardware.fans.get_mmio_fan_controller") as mock_get_ctrl,
    ):
        ctrl = MagicMock()
        mock_get_ctrl.return_value = ctrl
        telem = get_detailed_fan_telemetry()

        assert telem["mmio_supported"] is False
        ctrl.read_raw_registers.assert_not_called()


def test_button_listener_safeguards():
    from backend.services.button_listener import button_listener_daemon

    # Safeguard 1: Non-x86_64 returns immediately without mapping MMIO
    with (
        patch("platform.machine", return_value="aarch64"),
        patch("os.open") as mock_open,
    ):
        button_listener_daemon()
        mock_open.assert_not_called()

    # Safeguard 2: D4 chassis returns immediately without mapping MMIO
    with (
        patch("platform.machine", return_value="x86_64"),
        patch("backend.hardware.fans.is_zettlab_appliance", return_value=True),
        patch("backend.hardware.storage.detect_chassis_model", return_value="d4"),
        patch("os.open") as mock_open,
    ):
        button_listener_daemon()
        mock_open.assert_not_called()


# ==============================================================================
# 2. SQLite app_config Database Persistence Tests
# ==============================================================================


def test_app_config_db_crud():
    test_key = "test_feature_config"
    val = {"enabled": True, "threshold": 42, "tags": ["nas", "ups"]}

    set_app_config_value(test_key, val)
    retrieved = get_app_config_value(test_key)
    assert retrieved == val

    # Update value
    val["threshold"] = 99
    set_app_config_value(test_key, val)
    updated = get_app_config_value(test_key)
    assert updated["threshold"] == 99

    # Default fallback
    assert get_app_config_value("non_existent_key", default="fallback") == "fallback"


# ==============================================================================
# 3. Multi-Tier UPS Configuration Persistence & Recovery Tests
# ==============================================================================


def test_ups_save_config_persists_to_all_tiers():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary_file = os.path.join(tmpdir, "ups_config.json")
        backup_file = os.path.join(tmpdir, "ups_config.backup.json")
        pool_dir = os.path.join(tmpdir, "pool")
        os.makedirs(pool_dir, exist_ok=True)
        pool_mirror = os.path.join(pool_dir, ".zettnas", "ups_config.json")

        test_cfg = {
            "enabled": True,
            "mode": "nut_client",
            "host": "192.168.10.100",
            "port": 3493,
            "ups_name": "lab_ups",
            "shutdown_policy": "battery_pct",
            "battery_threshold_pct": 30,
        }

        with (
            patch("backend.hardware.ups.UPS_CONFIG_FILE", primary_file),
            patch("backend.hardware.ups.DATA_DIR", tmpdir),
            patch("backend.hardware.ups.POOL_PATH", pool_dir),
        ):
            saved = save_ups_config(test_cfg)
            assert saved["mode"] == "nut_client"
            assert saved["host"] == "192.168.10.100"

            # Tier 1: Primary JSON file
            assert os.path.exists(primary_file)
            with open(primary_file, "r") as f:
                p_data = json.load(f)
            assert p_data["host"] == "192.168.10.100"

            # Tier 2: SQLite database app_config
            db_data = get_app_config_value("ups_config")
            assert db_data is not None
            assert db_data["host"] == "192.168.10.100"

            # Tier 3: Local backup file
            assert os.path.exists(backup_file)
            with open(backup_file, "r") as f:
                b_data = json.load(f)
            assert b_data["host"] == "192.168.10.100"

            # Tier 4: Pool mirror
            assert os.path.exists(pool_mirror)
            with open(pool_mirror, "r") as f:
                m_data = json.load(f)
            assert m_data["host"] == "192.168.10.100"


def test_ups_load_config_recovers_from_sqlite_app_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary_file = os.path.join(tmpdir, "ups_config.json")

        # Pre-seed SQLite app_config
        db_cfg = {
            "enabled": True,
            "mode": "nut_client",
            "host": "192.168.50.20",
            "port": 3493,
            "ups_name": "synology_nut",
        }
        set_app_config_value("ups_config", db_cfg)

        with (
            patch("backend.hardware.ups.UPS_CONFIG_FILE", primary_file),
            patch("backend.hardware.ups.DATA_DIR", tmpdir),
            patch("backend.hardware.ups.POOL_PATH", None),
        ):
            loaded = load_ups_config()
            assert loaded["mode"] == "nut_client"
            assert loaded["host"] == "192.168.50.20"
            assert loaded["ups_name"] == "synology_nut"

            # Auto-sync back to primary file verified
            assert os.path.exists(primary_file)
            with open(primary_file, "r") as f:
                synced = json.load(f)
            assert synced["host"] == "192.168.50.20"


def test_ups_load_config_recovers_from_backup_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        primary_file = os.path.join(tmpdir, "ups_config.json")
        backup_file = os.path.join(tmpdir, "ups_config.backup.json")

        # Clear database
        set_app_config_value("ups_config", None)

        backup_cfg = {
            "enabled": True,
            "mode": "apcupsd_client",
            "host": "10.0.0.1",
            "port": 3551,
        }
        with open(backup_file, "w") as f:
            json.dump(backup_cfg, f)

        with (
            patch("backend.hardware.ups.UPS_CONFIG_FILE", primary_file),
            patch("backend.hardware.ups.DATA_DIR", tmpdir),
            patch("backend.hardware.ups.POOL_PATH", None),
        ):
            loaded = load_ups_config()
            assert loaded["mode"] == "apcupsd_client"
            assert loaded["host"] == "10.0.0.1"
            assert os.path.exists(primary_file)


def test_detect_host_nut_config():
    with tempfile.TemporaryDirectory() as tmpdir:
        upsmon_conf = os.path.join(tmpdir, "upsmon.conf")
        with open(upsmon_conf, "w") as f:
            f.write("""
# Host NUT monitoring configuration
MONITOR myups@10.20.30.40:3493 1 monuser secretpass master
MINSUPPLIES 1
SHUTDOWNCMD "/sbin/shutdown -h +0"
""")

        detected = _detect_host_nut_config(custom_dirs=[tmpdir])
        assert detected is not None
        assert detected["enabled"] is True
        assert detected["mode"] == "nut_client"
        assert detected["ups_name"] == "myups"
        assert detected["host"] == "10.20.30.40"
        assert detected["port"] == 3493
        assert detected["username"] == "monuser"
        assert detected["password"] == "secretpass"


def test_query_nut_socket_handles_unknown_ups_with_discovery():
    mock_socket = MagicMock()

    # Sequence of server responses:
    # 1. LIST VAR initial_ups -> returns ERR UNKNOWN-UPS
    # 2. LIST UPS -> returns discovered UPS list
    # 3. LIST VAR discovered_ups -> returns real variables
    server_lines = [
        b"ERR UNKNOWN-UPS\n",
        b"BEGIN LIST UPS\n",
        b'UPS actual_nut_device "CyberPower CP1500"\n',
        b"END LIST UPS\n",
        b"BEGIN LIST VAR actual_nut_device\n",
        b'VAR actual_nut_device ups.status "OL"\n',
        b'VAR actual_nut_device battery.charge "100"\n',
        b'VAR actual_nut_device battery.runtime "1800"\n',
        b'VAR actual_nut_device ups.model "CP1500PFCLCD"\n',
        b"END LIST VAR actual_nut_device\n",
    ]

    mock_socket.recv.side_effect = server_lines

    with patch("socket.socket") as mock_sock_cls:
        mock_sock_cls.return_value.__enter__.return_value = mock_socket
        result = _query_nut_socket(host="127.0.0.1", port=3493, ups_name="wrong_name")
        assert result is not None
        assert result.get("STATUS") == "OL"
        assert result.get("BCHARGE") == "100"
        assert result.get("MODEL") == "CP1500PFCLCD"
