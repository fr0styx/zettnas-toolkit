"""
ZettNAS Toolkit - Expanded UPS & Power Infrastructure Tests
Tests for multi-protocol HAL, persistent config management, auto-discovery,
connection testing, battery self-test, outage simulation, and event logs.
"""

import os
from unittest.mock import patch

from backend.config import UPS_CONFIG_FILE
from backend.db import init_db, log_ups_event, query_ups_events
from backend.hardware.ups import (
    DEFAULT_UPS_CONFIG,
    discover_ups_sources,
    load_ups_config,
    mask_ups_config,
    read_ups_status,
    run_ups_self_test,
    save_ups_config,
    test_ups_connection as exec_test_ups_connection,
)


def setup_function():
    init_db()
    if os.path.exists(UPS_CONFIG_FILE):
        try:
            os.remove(UPS_CONFIG_FILE)
        except Exception:
            pass


def teardown_function():
    if os.path.exists(UPS_CONFIG_FILE):
        try:
            os.remove(UPS_CONFIG_FILE)
        except Exception:
            pass


def test_default_config_loading_and_masking():
    cfg = load_ups_config()
    assert cfg["enabled"] is True
    assert cfg["mode"] == "auto"
    assert cfg["shutdown_policy"] == "runtime_left"

    cfg["password"] = "supersecret123"
    masked = mask_ups_config(cfg)
    assert masked["password"] == "********"


def test_save_ups_config_and_password_preservation():
    initial = {
        "enabled": True,
        "mode": "nut_client",
        "host": "10.0.0.50",
        "port": 3493,
        "ups_name": "homelab_ups",
        "password": "my_vault_password",
        "shutdown_policy": "battery_pct",
        "battery_threshold_pct": 25,
    }
    saved = save_ups_config(initial)
    assert saved["password"] == "********"
    assert saved["mode"] == "nut_client"
    assert saved["battery_threshold_pct"] == 25

    # Update other fields while passing masked password
    update = {
        "host": "10.0.0.55",
        "password": "********",
        "runtime_threshold_min": 8,
    }
    saved2 = save_ups_config(update)
    assert saved2["host"] == "10.0.0.55"
    assert saved2["runtime_threshold_min"] == 8

    # Raw read from disk must preserve original secret password
    raw = load_ups_config()
    assert raw["password"] == "my_vault_password"


@patch("backend.hardware.ups._query_apcupsd_socket")
def test_read_ups_status_enriched_telemetry(mock_apc):
    mock_apc.return_value = {
        "STATUS": "ONLINE",
        "MODEL": "Back-UPS Pro 1500",
        "BCHARGE": "98.5 Percent",
        "TIMELEFT": "42.0 Minutes",
        "LOADPCT": "18.0 Percent",
        "LINEV": "120.5 Volts",
        "BATTV": "26.8 Volts",
        "NOMPOWER": "900 Watts",
        "ITEMP": "29.4 C",
        "LINEFREQ": "60.0 Hz",
    }

    status = read_ups_status(force=True)
    assert status["available"] is True
    assert status["model"] == "Back-UPS Pro 1500"
    assert status["battery_charge_pct"] == 98.5
    assert status["time_left_min"] == 42.0
    assert status["load_pct"] == 18.0
    assert status["line_volts"] == 120.5
    assert status["battery_volts"] == 26.8
    assert status["battery_temp_c"] == 29.4
    assert status["line_freq_hz"] == 60.0
    assert status["power_watts"] == 162.0  # 18% of 900W


@patch("glob.glob")
@patch("backend.hardware.ups._query_apcupsd_socket")
@patch("backend.hardware.ups._query_nut_socket")
def test_discover_ups_sources(mock_nut, mock_apc, mock_glob):
    mock_glob.return_value = []
    mock_apc.return_value = {
        "MODEL": "APC Smart-UPS 1000",
        "STATUS": "ONLINE",
        "BCHARGE": "100.0",
    }
    mock_nut.return_value = {}

    candidates = discover_ups_sources()
    assert any(c["type"] == "apcupsd_client" for c in candidates)
    apc_cand = next(c for c in candidates if c["type"] == "apcupsd_client")
    assert apc_cand["model"] == "APC Smart-UPS 1000"


@patch("backend.hardware.ups._query_nut_socket")
def test_ups_connection_execution(mock_nut):
    mock_nut.return_value = {
        "MODEL": "CyberPower CP1500",
        "STATUS": "ONLINE",
        "BCHARGE": "100.0",
    }
    res = exec_test_ups_connection("192.168.1.100", 3493, mode="nut_client", ups_name="cyberpower")
    assert res["success"] is True
    assert res["model"] == "CyberPower CP1500"


def test_log_and_query_ups_events():
    init_db()
    ev_id = log_ups_event(
        event_type="POWER_OUTAGE",
        status="RESOLVED",
        duration_sec=45.2,
        start_battery_pct=100.0,
        end_battery_pct=92.0,
        min_line_volts=0.0,
        max_load_pct=22.0,
        action_taken="Mains restored; normal operation resumed.",
        details="Outage drill test",
    )
    assert ev_id > 0

    events = query_ups_events(limit=10)
    assert len(events) >= 1
    found = next((e for e in events if e["id"] == ev_id), None)
    assert found is not None
    assert found["event_type"] == "POWER_OUTAGE"
    assert found["duration_sec"] == 45.2


def test_api_endpoints_ups_telemetry_and_events(client, auth_headers):
    # 1. GET /api/ups
    res = client.get("/api/ups", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "available" in data
    assert "status" in data

    # 2. GET /api/ups/config
    res_cfg = client.get("/api/ups/config", headers=auth_headers)
    assert res_cfg.status_code == 200
    cfg_data = res_cfg.json()
    assert "mode" in cfg_data
    assert "shutdown_policy" in cfg_data

    # 3. GET /api/ups/events
    res_ev = client.get("/api/ups/events", headers=auth_headers)
    assert res_ev.status_code == 200
    ev_data = res_ev.json()
    assert "events" in ev_data
