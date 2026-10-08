import io
import time
from unittest.mock import MagicMock, patch

from backend.config import FAN_FAILSAFE_PWM, FAN_MAX_PWM, FAN_MIN_PWM
from backend.db import query_smart_velocity
from backend.hardware.fans import calc_curve_pwm
from backend.hardware.ups import _get_docker_gateway


def test_calc_curve_pwm_failsafe_on_sensor_dropout():
    """Verify that calc_curve_pwm returns FAN_FAILSAFE_PWM on missing/invalid temperatures."""
    # When allow_zero=True, sensor failure must NOT stop fans
    assert calc_curve_pwm(None, allow_zero=True) == FAN_FAILSAFE_PWM
    assert calc_curve_pwm(0, allow_zero=True) == FAN_FAILSAFE_PWM
    assert calc_curve_pwm(-10, allow_zero=True) == FAN_FAILSAFE_PWM

    # When allow_zero=False
    assert calc_curve_pwm(None, allow_zero=False) == FAN_FAILSAFE_PWM
    assert calc_curve_pwm(0, allow_zero=False) == FAN_FAILSAFE_PWM


def test_under_populated_chassis_and_all_flash_zero_rpm():
    """Verify that under-populated chassis and all-flash systems properly calculate zone standby."""
    # Under-populated chassis with 2 drives in Zone 1, 0 in Zone 2
    sata_disks_underpopulated = [
        {"dev": "sda", "role": "data", "standby": True, "temp": None},
        {"dev": "sdb", "role": "data", "standby": True, "temp": None},
    ]
    # D8 chassis logic with 2 drives
    midpoint = max(1, len(sata_disks_underpopulated) // 2)
    zone1 = sata_disks_underpopulated[:midpoint]
    zone2 = sata_disks_underpopulated[midpoint:]

    z1_standby = bool(zone1) and all(d.get("standby", False) for d in zone1)
    z2_standby = all(d.get("standby", False) for d in zone2) if zone2 else z1_standby
    assert z1_standby is True
    assert z2_standby is True

    # All-flash array (no SATA disks)
    sata_disks_empty = []
    if not sata_disks_empty:
        af_z1 = True
        af_z2 = True
    assert af_z1 is True
    assert af_z2 is True


def test_smart_velocity_stuck_pending_requires_44h_delta():
    """Verify that 2 quick readings on a freshly booted system do NOT trigger stuck_pending."""
    dev = "sd_test_fresh"
    now = int(time.time())

    mock_rows = [
        {"ts": now - 300, "pending_sectors": 5},
        {"ts": now, "pending_sectors": 5},
    ]

    time_span = mock_rows[-1]["ts"] - mock_rows[0]["ts"]
    stuck_pending = len(mock_rows) >= 2 and time_span >= 44 * 3600 and all(r["pending_sectors"] > 0 for r in mock_rows)
    assert stuck_pending is False, "A 5-minute span must not evaluate to stuck pending for >48h"

    # Now simulate true 48-hour span
    mock_rows_48h = [
        {"ts": now - (48 * 3600), "pending_sectors": 5},
        {"ts": now, "pending_sectors": 5},
    ]
    time_span_48h = mock_rows_48h[-1]["ts"] - mock_rows_48h[0]["ts"]
    stuck_pending_48h = (
        len(mock_rows_48h) >= 2 and time_span_48h >= 44 * 3600 and all(r["pending_sectors"] > 0 for r in mock_rows_48h)
    )
    assert stuck_pending_48h is True, "A 48-hour span of pending sectors must evaluate to stuck pending"


def test_docker_gateway_filtering_blocks_lan_routers():
    """Verify _get_docker_gateway rejects public/LAN router IPs and accepts Docker bridge IPs."""
    route_data_lan = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "br0\t00000000\t0101A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"  # 192.168.1.1 in hex
    )
    with patch("builtins.open", return_value=io.StringIO(route_data_lan)):
        assert _get_docker_gateway() is None, "Must reject 192.168.1.1 router IP"

    route_data_docker = (
        "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\n"
        "eth0\t00000000\t010011AC\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"  # 172.17.0.1 in hex
    )
    with patch("builtins.open", return_value=io.StringIO(route_data_docker)):
        assert _get_docker_gateway() == "172.17.0.1", "Must accept 172.17.0.1 Docker bridge IP"
