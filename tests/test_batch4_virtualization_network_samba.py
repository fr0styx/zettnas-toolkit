import os
import shutil
import subprocess
from unittest.mock import MagicMock, mock_open, patch

import pytest

from backend.hardware.network import (
    _format_speed,
    _get_wireguard_status,
    get_active_listening_ports,
)
from backend.services.samba_engine import SambaEngine, get_samba_engine
from backend.users_db import create_user, delete_user, init_users_db, update_user_password


def test_5gbe_speed_detection():
    """Verifies _format_speed correctly detects 5GbE before 2.5GbE."""
    assert _format_speed(5000, is_up=True) == "5 Gbps"
    assert _format_speed(2500, is_up=True) == "2.5 Gbps"
    assert _format_speed(10000, is_up=True) == "10 Gbps"
    assert _format_speed(1000, is_up=True) == "1 Gbps"
    assert _format_speed(100, is_up=True) == "100 Mbps"
    assert _format_speed(0, is_up=False) == "Disconnected"
    assert _format_speed(None, is_up=True) == "Unknown"


def test_wireguard_telemetry_dump_parsing():
    """Verifies _get_wireguard_status parses wg show all dump and scrubs preshared keys."""
    fake_dump = (
        "wg0\tPRIVATE_KEY_HIDDEN\tPUBLIC_KEY_1111\t51820\toff\n"
        "wg0\tPEER_PUBKEY_AAAABBBBCCCC\tSECRET_PSK_MUST_REDACT\t198.51.100.2:51820\t10.0.0.2/32\t1700000000\t1048576\t2097152\t25\n"
        "wg0\tPEER_PUBKEY_DDDDEEEEFFFF\t(none)\t(none)\t10.0.0.3/32\t0\t0\t0\toff\n"
    )

    def fake_run(cmd, *args, **kwargs):
        m = MagicMock()
        m.returncode = 0
        if cmd == ["wg", "show", "interfaces"]:
            m.stdout = "wg0\n"
        elif cmd == ["wg", "show", "all", "dump"]:
            m.stdout = fake_dump
        else:
            m.stdout = ""
        return m

    with patch("subprocess.run", side_effect=fake_run), patch("time.time", return_value=1700000050):
        status = _get_wireguard_status()
        assert status["installed"] is True
        assert status["active"] is True
        assert status["interfaces"] == ["wg0"]
        assert status["peers_count"] == 2

        p1 = status["peers"][0]
        assert "SECRET_PSK_MUST_REDACT" not in str(status)
        assert p1["endpoint"] == "198.51.100.2:51820"
        assert p1["allowed_ips"] == ["10.0.0.2/32"]
        assert p1["latest_handshake"] == 1700000000
        assert p1["latest_handshake_age"] == 50
        assert p1["active"] is True
        assert p1["transfer_rx_bytes"] == 1048576
        assert p1["transfer_tx_bytes"] == 2097152

        p2 = status["peers"][1]
        assert p2["active"] is False
        assert p2["endpoint"] == ""


def test_listening_ports_discovery():
    """Verifies get_active_listening_ports parses /proc/net/tcp and correlates services."""
    tcp_sample = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:1F92 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1774435 1 00000000d58fed9c 100 0 0 10 0\n"
        "   1: 0100007F:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1774436 1 00000000d58fed9d 100 0 0 10 0\n"
        "   2: 0100007F:1F92 0100007F:CC56 01 00000000:00000000 00:00000000 00000000     0        0 1774437 1 00000000d58fed9e 100 0 0 10 0\n"
    )

    fake_containers = [
        {"id": "cid123456789", "name": "zettnas-toolkit", "ports": [{"host_port": 8082, "proto": "tcp"}]}
    ]

    def mock_file_open(path, *args, **kwargs):
        p_str = str(path)
        if "tcp" in p_str and "tcp6" not in p_str:
            return mock_open(read_data=tcp_sample)()
        return mock_open(read_data="")()

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", side_effect=mock_file_open),
        patch("backend.hardware.docker_stats.read_docker_containers", return_value=fake_containers),
    ):
        ports = get_active_listening_ports()
        assert len(ports) >= 2

        p_8082 = next((p for p in ports if p["port"] == 8082), None)
        assert p_8082 is not None
        assert p_8082["protocol"] == "tcp"
        assert p_8082["bind_address"] == "0.0.0.0"
        assert p_8082["state"] == "LISTEN"
        assert p_8082["container"] == "zettnas-toolkit"

        p_22 = next((p for p in ports if p["port"] == 22), None)
        assert p_22 is not None
        assert p_22["service"] == "SSH"
        assert p_22["bind_address"] == "127.0.0.1"


def test_samba_passdb_sync_lifecycle():
    """Verifies sync_samba_user interacts with sidecar container or local passdb."""
    engine = SambaEngine()

    mock_client = MagicMock()
    mock_client.post.return_value.status_code = 201
    mock_client.post.return_value.json.return_value = {"Id": "exec123"}
    mock_client.__enter__.return_value = mock_client

    with (
        patch.object(engine, "check_sidecar", return_value={"detected": True, "id": "zettnas-samba"}),
        patch("os.path.exists", return_value=True),
        patch("httpx.Client", return_value=mock_client),
    ):
        ok = engine.sync_samba_user("nasuser", password="secretpassword")
        assert ok is True
        assert mock_client.post.call_count >= 2

        ok_del = engine.sync_samba_user("nasuser", delete=True)
        assert ok_del is True


def test_users_db_samba_sync_hooks(tmp_path):
    """Verifies user creation, password update, and deletion invoke samba passdb sync."""
    db_file = str(tmp_path / "test_users.db")
    init_users_db(db_file)

    with patch("backend.services.samba_engine.get_samba_engine") as mock_engine_fn:
        mock_engine = MagicMock()
        mock_engine_fn.return_value = mock_engine

        # Create user
        user_doc = create_user(
            "alice", "Alice Wonder", "mypass123", email="alice@example.com", role_id="share_user", db_path=db_file
        )
        uid = user_doc["id"]
        assert uid is not None
        mock_engine.sync_samba_user.assert_called_with(username="alice", password="mypass123")

        # Update password
        mock_engine.reset_mock()
        ok_upd = update_user_password(uid, "newsecret456", db_path=db_file)
        assert ok_upd is True
        mock_engine.sync_samba_user.assert_called_with(username="alice", password="newsecret456")

        # Delete user
        mock_engine.reset_mock()
        ok_del = delete_user(uid, db_path=db_file)
        assert ok_del is True
        mock_engine.sync_samba_user.assert_called_with(username="alice", delete=True)


def test_vm_disk_expansion_and_raw_format(tmp_path):
    """Verifies VM disk resize properly detects raw format and QMP device target."""
    import backend.api.vms as vms_mod
    from backend.api.vms import VmDiskResizeRequest, delete_vm, resize_vm_disk

    vm_id = "test-vm-raw"
    vm_dir = tmp_path / "vms" / vm_id
    vm_dir.mkdir(parents=True)
    raw_disk = vm_dir / "disk.raw"
    raw_disk.write_bytes(b"\0" * 1024)

    mock_vm = {
        "id": vm_id,
        "name": "RawVM",
        "disk_path": str(raw_disk),
        "disk_format": "raw",
        "disk_size_gb": 10,
        "state": "stopped",
    }

    commands_run = []

    def fake_subprocess_run(cmd, *args, **kwargs):
        commands_run.append(cmd)
        m = MagicMock()
        m.returncode = 0
        return m

    with (
        patch("backend.services.vm_qemu._load_vms", return_value=[mock_vm]),
        patch("backend.services.vm_qemu._save_vms"),
        patch.object(vms_mod, "DATA_DIR", str(tmp_path)),
        patch("subprocess.run", side_effect=fake_subprocess_run),
        patch("shutil.which", return_value="/usr/bin/qemu-img"),
    ):
        req = VmDiskResizeRequest(new_size_gb=20, disk_index=0)
        res = resize_vm_disk(vm_id, req)
        assert res["status"] == "ok"
        assert res["new_size_gb"] == 20

        # Verify -f raw was used in qemu-img resize
        resize_cmd = next(c for c in commands_run if "resize" in c)
        assert "-f" in resize_cmd
        assert "raw" in resize_cmd

        # Test delete_vm purges directory
        del_res = delete_vm(vm_id, purge_disks=True)
        assert del_res["status"] == "ok"
        assert not vm_dir.exists()
