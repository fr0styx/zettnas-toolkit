"""SET-08: one empty value in the stored fan settings stopped the whole two-second loop. Empty
values are refused when they are sent, and stored settings are read defensively."""

import json

import pytest

from backend.api import fans as fans_api
from backend.hardware.fans import usable_fan_settings
from backend.services import fan_control

DEFAULTS = {"profile": "auto", "manual_pct": 60, "ctrl_cpu_fan": False, "zero_rpm_stop_delay": 60}


@pytest.mark.parametrize(
    "saved, expected",
    [
        ({"zero_rpm_stop_delay": None}, DEFAULTS),  # the value that froze the loop
        ({"zero_rpm_stop_delay": "soon"}, DEFAULTS),
        ({"manual_pct": True}, DEFAULTS),  # a switch is not a number
        ({"ctrl_cpu_fan": "yes"}, DEFAULTS),
        ({"profile": 3}, DEFAULTS),
        ("not a dict", DEFAULTS),
        (None, DEFAULTS),
        ({"manual_pct": 45, "ctrl_cpu_fan": True}, {**DEFAULTS, "manual_pct": 45, "ctrl_cpu_fan": True}),
        ({"zero_rpm_stop_delay": 12.5}, {**DEFAULTS, "zero_rpm_stop_delay": 12.5}),
        ({"zero_rpm_stop_delay": "45"}, {**DEFAULTS, "zero_rpm_stop_delay": 45}),  # a number saved as text
        ({"curve_points": [[30, 32], [60, 100]]}, {**DEFAULTS, "curve_points": [[30, 32], [60, 100]]}),
        ({"curve_points": None}, DEFAULTS),
    ],
)
def test_what_can_not_be_used_falls_back_to_its_default(saved, expected):
    assert usable_fan_settings(saved, DEFAULTS) == expected


def test_the_fan_loop_reads_a_damaged_file_without_failing(tmp_path, monkeypatch):
    path = tmp_path / "fans.json"
    path.write_text(
        json.dumps({"profile": "quiet", "zero_rpm_stop_delay": None, "disk_hold_secs": "x", "cpu_hold_secs": None})
    )
    monkeypatch.setattr(fan_control, "FAN_STATE_FILE", str(path))
    monkeypatch.setattr(fan_control, "read_json_cached", lambda p, default, max_age=0: json.loads(path.read_text()))
    got = fan_control.fan_settings()  # raised TypeError: int() argument must be ... not 'NoneType'
    assert got["profile"] == "quiet"
    assert isinstance(got["zero_rpm_stop_delay"], int) and isinstance(got["disk_hold_secs"], int)
    assert isinstance(got["cpu_hold_secs"], int)


def test_an_empty_value_is_refused_and_nothing_is_saved(client, auth_headers, tmp_path, monkeypatch):
    path = tmp_path / "fans.json"
    path.write_text(json.dumps({"profile": "auto", "manual_pct": 55}))
    monkeypatch.setattr(fans_api, "FAN_STATE_FILE", str(path))
    r = client.post("/api/fans", json={"zero_rpm_stop_delay": None, "profile": "quiet"}, headers=auth_headers)
    assert r.status_code == 400 and "zero_rpm_stop_delay" in r.json()["detail"]
    assert json.loads(path.read_text()) == {"profile": "auto", "manual_pct": 55}

    r = client.post("/api/fans", json={"zero_rpm_enabled": True}, headers=auth_headers)
    assert r.status_code == 200
    saved = json.loads(path.read_text())
    assert saved["zero_rpm_enabled"] is True and saved["profile"] == "auto" and saved["manual_pct"] == 55
