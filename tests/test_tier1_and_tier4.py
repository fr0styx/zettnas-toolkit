"""
Unit and Integration Tests for Strategic Roadmap Tier 1 and Tier 4:
- Tier 1: Automated Snapshot Replication Engine, WireGuard Client Config & Subnet Router
- Tier 4: Hardware-Gated Smart Media Engine (< 8GB RAM gate), Appliance Bridges
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from backend.hardware.network import (
    generate_wireguard_client_config,
    generate_wireguard_keypair,
    get_ip_forwarding_status,
    set_ip_forwarding,
    toggle_wireguard_subnet_nat,
)
from backend.hardware.chassis import ChassisEngine
from backend.services.media_engine import MediaEngine, detect_hardware_accelerator, read_total_ram_bytes
from backend.services.replication_engine import ReplicationEngine, ReplicationJob


@pytest.fixture
def mock_replication_engine(tmp_path, monkeypatch):
    jobs_file = str(tmp_path / "replication_jobs.json")
    hist_file = str(tmp_path / "replication_history.json")
    monkeypatch.setattr("backend.services.replication_engine.REPLICATION_JOBS_FILE", jobs_file)
    monkeypatch.setattr("backend.services.replication_engine.REPLICATION_HISTORY_FILE", hist_file)
    return ReplicationEngine()


def test_replication_job_lifecycle(mock_replication_engine):
    engine = mock_replication_engine
    assert engine.list_jobs() == []

    # Create job
    job = engine.create_job(
        {
            "name": "Offsite Vault Backup",
            "source_pool": "ark",
            "source_dataset": "vault",
            "target_type": "remote_ssh",
            "target_host": "10.40.30.250",
            "target_port": 22,
            "target_user": "backupuser",
            "target_pool": "backup_pool",
            "target_dataset": "ark_vault",
            "bandwidth_limit_kbps": 20000,
            "incremental": True,
            "retention_count": 30,
        }
    )

    assert job["name"] == "Offsite Vault Backup"
    assert job["target_host"] == "10.40.30.250"
    assert job["bandwidth_limit_kbps"] == 20000
    assert job["last_status"] == "idle"

    # List
    jobs = engine.list_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job["id"]

    # Status update
    engine.update_job_status(job["id"], "success", bytes_transferred=1048576)
    updated = engine.get_job(job["id"])
    assert updated["last_status"] == "success"
    assert updated["bytes_transferred"] == 1048576

    # History
    history = engine.get_history()
    assert len(history) == 1
    assert history[0]["status"] == "success"

    # Delete
    assert engine.delete_job(job["id"]) is True
    assert len(engine.list_jobs()) == 0


def test_replication_run_async_not_found(mock_replication_engine):
    engine = mock_replication_engine
    with pytest.raises(ValueError, match="not found"):
        engine.run_job_async("nonexistent-job-id")


def test_wireguard_keypair_generation():
    priv, pub = generate_wireguard_keypair()
    assert isinstance(priv, str) and len(priv) >= 32
    assert isinstance(pub, str) and len(pub) >= 32


def test_wireguard_client_config_generation():
    res = generate_wireguard_client_config(
        client_name="macbook-pro",
        client_ip="10.13.13.5/32",
        server_endpoint="nas.mydomain.com:51820",
        server_pubkey="server-public-key-example",
        dns="1.1.1.1",
        allowed_ips="0.0.0.0/0, ::/0",
    )

    assert res["client_name"] == "macbook-pro"
    assert res["client_ip"] == "10.13.13.5/32"
    conf = res["config_text"]
    assert "[Interface]" in conf
    assert "[Peer]" in conf
    assert "Endpoint = nas.mydomain.com:51820" in conf
    assert "AllowedIPs = 0.0.0.0/0, ::/0" in conf


def test_wireguard_subnet_routing(monkeypatch):
    monkeypatch.setattr("backend.hardware.network.set_ip_forwarding", lambda x: True)
    res = toggle_wireguard_subnet_nat(True, iface="wg0", out_iface="eth0")
    assert res["enabled"] is True
    assert res["ip_forwarding"] is True


def test_media_engine_ram_gating(monkeypatch):
    engine = MediaEngine()

    # Case 1: Under 8GB RAM (< 8GB)
    monkeypatch.setattr(
        "backend.services.media_engine.read_total_ram_bytes",
        lambda: 4 * 1024 * 1024 * 1024,
    )
    status = engine.get_status()
    assert status["is_gated"] is True
    assert status["total_ram_gb"] == 4.0
    assert "Insufficient host RAM" in status["gate_reason"]

    with pytest.raises(PermissionError, match="Insufficient host RAM"):
        engine.trigger_scan("/tmp/media")

    # Case 2: 16GB RAM (>= 8GB)
    monkeypatch.setattr(
        "backend.services.media_engine.read_total_ram_bytes",
        lambda: 16 * 1024 * 1024 * 1024,
    )
    status2 = engine.get_status()
    assert status2["is_gated"] is False
    assert status2["gate_reason"] is None


def test_media_engine_hardware_acceleration(monkeypatch):
    # Mock NPU node present
    with patch("os.path.exists", side_effect=lambda p: p in ("/dev/accel/accel0")):
        accel = detect_hardware_accelerator()
        assert accel["has_npu"] is True
        assert accel["acceleration_backend"] == "intel_npu"


def test_chassis_appliance_bridges():
    bridges = ChassisEngine.get_appliance_bridge_status()
    assert "platform_bridges" in bridges
    assert "zettlabs" in bridges["platform_bridges"]
    assert "aoostar" in bridges["platform_bridges"]
    assert "ugreen" in bridges["platform_bridges"]
    assert "cwwk_topton" in bridges["platform_bridges"]
