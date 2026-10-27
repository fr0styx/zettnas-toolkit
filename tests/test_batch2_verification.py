"""
Verification test suite for Batch 2:
- Snapshot replication routing (/api/storage/replication/jobs)
- Storage overview and unassigned disks (/api/storage/overview, /api/storage/disks)
- Legacy system disks compatibility (/api/system/disks)
- Host system power triggers (reboot & shutdown)
- Prometheus telemetry gauge extractions
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


def test_replication_router_endpoints(client, auth_headers, tmp_path, monkeypatch):
    """REL-5: replication runs only where ZettNAS manages the pools with their tools; elsewhere
    listing still works and creating or running a job says why."""
    monkeypatch.setattr("backend.services.replication_engine.REPLICATION_JOBS_FILE", str(tmp_path / "jobs.json"))
    monkeypatch.setattr("backend.services.replication_engine.REPLICATION_HISTORY_FILE", str(tmp_path / "hist.json"))
    res = client.get("/api/storage/replication/jobs", headers=auth_headers)
    assert res.status_code == 200 and res.json()["available"] is False and "jobs" in res.json()
    why = res.json()["reason"]
    payload = {
        "name": "DR",
        "source_pool": "tank",
        "source_dataset": "data",
        "target_type": "local",
        "target_pool": "backup_pool",
        "target_dataset": "replicated",
        "schedule": "daily",
        "retention_count": 7,
    }
    created = client.post("/api/storage/replication/jobs", json=payload, headers=auth_headers)
    assert created.status_code == 409 and created.json()["detail"] == why
    assert client.post("/api/storage/replication/jobs/any/run", headers=auth_headers).status_code == 409
    assert client.get("/api/storage/replication/history", headers=auth_headers).status_code == 200


def test_storage_overview_and_disks_endpoints(client, auth_headers):
    # Storage overview
    res = client.get("/api/storage/overview", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "pools" in data
    assert "shares" in data
    assert "disks" in data
    assert "unassigned_disks" in data

    # Storage disks
    res_disks = client.get("/api/storage/disks", headers=auth_headers)
    assert res_disks.status_code == 200
    assert "disks" in res_disks.json()

    # System disks compatibility
    res_sys = client.get("/api/system/disks", headers=auth_headers)
    assert res_sys.status_code == 200
    assert "disks" in res_sys.json()


def test_system_power_action_dispatch(monkeypatch):
    from backend.api.system import trigger_power_action

    with (
        patch("backend.api.system.subprocess.Popen") as mock_popen,
        patch("shutil.which", return_value="/bin/poweroff"),
    ):
        ok = trigger_power_action("shutdown")
        assert ok is True


def test_prometheus_metrics_with_live_stats(monkeypatch):
    from backend.api.metrics import prometheus_metrics
    from backend.state import Z_STATE

    # Set up cached stats matching stats_collector schema
    Z_STATE.cached_stats = {
        "cpu": {"temp": 45, "util": 12.5, "power_w": 18.2},
        "mem": {"total_gb": 32.0, "used_gb": 8.0, "pct": 25},
        "net": {
            "rx_bytes": 1000000,
            "tx_bytes": 500000,
            "rx_bytes_sec": 1024.0,
            "tx_bytes_sec": 2048.0,
            "interfaces": {
                "eth0": {"rx_bytes": 1000000, "tx_bytes": 500000, "rx_bytes_sec": 1024.0, "tx_bytes_sec": 2048.0}
            },
        },
        "disks": [{"name": "sda", "role": "data", "temp": 32, "io_ticks": 100}],
        "fans": [1200, 1150],
        "ups": {"available": False},
        "unraid": {"available": False},
    }

    metrics_text = prometheus_metrics()
    assert "zettnas_cpu_usage_percent 12.5" in metrics_text
    assert "zettnas_memory_usage_percent 25" in metrics_text
    assert "zettnas_network_combined_rx_bytes_sec 1024.0" in metrics_text
