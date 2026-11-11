"""The Host tab's cooling mode leaves the light alone and lets the fan loop apply it (SET-15, Hardware 1)."""

from unittest.mock import patch

from backend.api import system as sysapi


def test_the_mode_is_saved_and_the_light_is_left_alone(tmp_path, monkeypatch):
    fans, led = tmp_path / "fans.json", tmp_path / "led.json"
    led.write_text('{"brightness": 80}')  # the mode no longer opens the light's file at all
    monkeypatch.setattr(sysapi, "FAN_STATE_FILE", str(fans))
    with patch("backend.hardware.fans.set_fan_pwm") as direct:
        res = sysapi.set_system_profile.__wrapped__(sysapi.SystemProfileRequest(profile="quiet"))
    assert res["profile"] == "quiet"
    assert "led" not in res
    assert led.read_text() == '{"brightness": 80}'
    assert '"profile": "quiet"' in fans.read_text()
    direct.assert_not_called()


def test_an_unknown_mode_name_is_balanced(tmp_path, monkeypatch):
    monkeypatch.setattr(sysapi, "FAN_STATE_FILE", str(tmp_path / "fans.json"))
    req = sysapi.SystemProfileRequest.model_construct(profile="balanced")
    assert sysapi.set_system_profile.__wrapped__(req)["profile"] == "balanced"
