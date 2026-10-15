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


def test_parse_hid_report_descriptor():
    from backend.hardware.ups import _parse_hid_report_descriptor

    # Standard HID Power Device descriptor excerpt:
    # Usage Page (Power Device 0x84), Usage (Present Status 0x02), Collection...
    # Usage Page (Battery System 0x85), Usage (RemainingCapacity 0x66), Report Size (8), Report Count (1), Feature (0x02)
    sample_desc = bytes(
        [
            0x05,
            0x85,  # Usage Page (Battery System 0x85)
            0x09,
            0x66,  # Usage (RemainingCapacity 0x66)
            0x75,
            0x08,  # Report Size (8)
            0x95,
            0x01,  # Report Count (1)
            0x85,
            0x01,  # Report ID (1)
            0xB1,
            0x02,  # Feature
            0x09,
            0x68,  # Usage (RunTimeToEmpty 0x68)
            0x75,
            0x10,  # Report Size (16)
            0x95,
            0x01,  # Report Count (1)
            0x85,
            0x02,  # Report ID (2)
            0xB1,
            0x02,  # Feature
        ]
    )
    mapping = _parse_hid_report_descriptor(sample_desc)
    assert (0x85, 0x66) in mapping
    assert mapping[(0x85, 0x66)] == (1, 8, 1)  # (report_id, report_size, report_count)
    assert (0x85, 0x68) in mapping
    assert mapping[(0x85, 0x68)] == (2, 16, 1)


@patch("backend.hardware.ups._query_direct_usb")
def test_direct_usb_query_status(mock_direct):
    mock_direct.return_value = {
        "MODEL": "Smart UPS W180",
        "MFR": "WalleCube",
        "STATUS": "ONLINE",
        "BCHARGE": "100",
        "TIMELEFT": "180.0",
        "LINEV": "120",
        "LOADPCT": "12",
        "PROTOCOL": "direct_usb_hid",
    }
    save_ups_config({"mode": "usb_hid"})
    status = read_ups_status(force=True)
    assert status["available"] is True
    assert status["model"] == "Smart UPS W180"
    assert status["battery_charge_pct"] == 100.0
    assert status["time_left_min"] == 180.0
    assert status["protocol"] == "direct_usb_hid"
    assert status["power_watts"] == 21.6  # 12% of 180W nominal


@patch("backend.hardware.ups._query_direct_usb")
def test_direct_usb_permission_error_handling(mock_direct):
    mock_direct.return_value = {
        "MODEL": "Smart UPS W180",
        "MFR": "WalleCube",
        "STATUS": "PERMISSION_REQUIRED",
        "PROTOCOL": "direct_usb_hid",
        "PERMISSION_ERROR": True,
        "ERROR": "Docker lacks permission to open /dev/hidraw0.",
    }
    save_ups_config({"mode": "usb_hid"})
    status = read_ups_status(force=True)
    assert status["available"] is True
    assert status["permission_error"] is True
    assert status["status"] == "Permission Required"
    assert "Docker lacks permission" in status["permission_detail"]


@patch("backend.hardware.ups._query_direct_usb")
def test_test_ups_connection_direct_usb(mock_direct):
    mock_direct.return_value = {
        "MODEL": "Smart UPS W180",
        "STATUS": "ONLINE",
        "BCHARGE": "95",
        "PROTOCOL": "direct_usb_hid",
    }
    res = exec_test_ups_connection(mode="usb_hid")
    assert res["success"] is True
    assert res["connected"] is True
    assert res["model"] == "Smart UPS W180"
    assert res["battery_charge_pct"] == 95.0


@patch("backend.hardware.ups._query_direct_usb")
def test_w180_synthetic_power_and_load_derivation(mock_direct):
    # W180 mini-UPS provides raw output voltage & current, but leaves ups.load null
    mock_direct.return_value = {
        "MODEL": "Smart UPS W180",
        "MFR": "WalleCube",
        "STATUS": "ONLINE",
        "BCHARGE": "100",
        "TIMELEFT": "120.0",
        "OUTV": "12.0",
        "OUTCURR": "2.5",
        "PROTOCOL": "direct_usb_hid",
    }
    save_ups_config({"mode": "usb_hid"})
    status = read_ups_status(force=True)
    assert status["available"] is True
    assert status["model"] == "Smart UPS W180"
    assert status["nominal_power_watts"] == 180.0
    assert status["output_volts"] == 12.0
    assert status["output_amps"] == 2.5
    # 12.0V * 2.5A = 30.0W
    assert status["power_watts"] == 30.0
    # (30.0W / 180W) * 100 = 16.7%
    assert status["load_pct"] == 16.7


@patch("backend.hardware.ups._query_direct_usb")
def test_w180_realpower_derivation(mock_direct):
    mock_direct.return_value = {
        "MODEL": "Smart UPS W180",
        "MFR": "WalleCube",
        "STATUS": "ONLINE",
        "BCHARGE": "90",
        "TIMELEFT": "95.0",
        "REALPOWER": "45.0",
        "PROTOCOL": "direct_usb_sysfs",
    }
    save_ups_config({"mode": "usb_hid"})
    status = read_ups_status(force=True)
    assert status["available"] is True
    assert status["nominal_power_watts"] == 180.0
    assert status["power_watts"] == 45.0
    # (45.0W / 180W) * 100 = 25.0%
    assert status["load_pct"] == 25.0


@patch("backend.hardware.ups._query_direct_usb")
def test_w180_battery_voltage_fallback_when_output_voltage_missing(mock_direct):
    # If OUTV is not explicit, fallback to BATTV * OUTCURR
    mock_direct.return_value = {
        "MODEL": "Smart UPS W180",
        "STATUS": "ONLINE",
        "BATTV": "12.5",
        "OUTCURR": "2.0",
        "PROTOCOL": "direct_usb_sysfs",
    }
    save_ups_config({"mode": "usb_hid"})
    status = read_ups_status(force=True)
    assert status["power_watts"] == 25.0  # 12.5V * 2.0A
    assert status["load_pct"] == 13.9  # (25.0 / 180.0) * 100 = 13.88% -> 13.9%


@patch("subprocess.run")
def test_nut_cli_parsing_output_voltage_and_current(mock_run):
    from backend.hardware.ups import _query_nut_cli

    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = """
battery.charge: 99.0
battery.runtime: 3600
battery.voltage: 12.6
output.voltage: 12.0
output.current: 1.8
output.realpower: 21.6
ups.status: OL
ups.model: Smart UPS W180
ups.realpower.nominal: 180
"""
    res = _query_nut_cli("w180")
    assert res.get("OUTV") == "12.0"
    assert res.get("OUTCURR") == "1.8"
    assert res.get("REALPOWER") == "21.6"
    assert res.get("BCHARGE") == "99.0"
    assert res.get("MODEL") == "Smart UPS W180"
    assert res.get("NOMPOWER") == "180"


def test_nut_socket_parsing_expanded_dc_variables():
    from backend.hardware.ups import _query_nut_socket

    mock_lines = [
        'UPS w180 "DC UPS"',
        "END LIST UPS",
        'VAR w180 battery.charge "95"',
        'VAR w180 battery.current "2.2"',
        'VAR w180 output.voltage "12.2"',
        'VAR w180 output.power.percent "15"',
        'VAR w180 output.realpower.nominal "180"',
        'VAR w180 ups.status "OL"',
        "END LIST VAR w180",
    ]

    class FakeSocket:
        def __init__(self):
            self.data = ("\n".join(mock_lines) + "\n").encode("utf-8")
            self.pos = 0

        def connect(self, addr):
            pass

        def sendall(self, data):
            pass

        def recv(self, bufsize):
            if self.pos >= len(self.data):
                return b""
            chunk = self.data[self.pos : self.pos + bufsize]
            self.pos += len(chunk)
            return chunk

        def settimeout(self, t):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch("socket.socket", return_value=FakeSocket()):
        res = _query_nut_socket("127.0.0.1", 3493)
        assert res.get("BCHARGE") == "95"
        assert res.get("BATTCURR") == "2.2"
        assert res.get("OUTV") == "12.2"
        assert res.get("LOADPCT") == "15"
        assert res.get("NOMPOWER") == "180"
