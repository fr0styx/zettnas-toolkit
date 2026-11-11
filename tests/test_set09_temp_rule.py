"""SET-09: Drive Health uses the limits the alerts and the fans act on."""

from backend.config import SETTINGS
from backend.services import drive_health


def test_too_hot_is_where_the_fans_are_forced_to_full_speed():
    assert drive_health.usual_limits(False) == (SETTINGS.hdd_warn_temp, SETTINGS.hdd_critical_temp)
    assert drive_health.usual_limits(True) == (SETTINGS.nvme_warn_temp, SETTINGS.nvme_critical_temp)
    assert drive_health.temp_limits({}, False) == drive_health.usual_limits(False)
    assert drive_health.temp_limits({}, True) == drive_health.usual_limits(True)


def test_a_drives_own_limit_still_wins():
    assert drive_health.temp_limits({"temp_limit": 45}, False) == (45, 55)


def test_a_hard_drive_at_56_degrees_is_too_hot_not_warm():
    out = []
    drive_health._rules_heat(out, {"temp_c": 56}, False)  # the limit was 60 °C here, 55 for the fans
    assert [f["code"] for f in out] == ["too_hot"]
    out = []
    drive_health._rules_heat(out, {"temp_c": 76}, True)
    assert [f["code"] for f in out] == ["too_hot"]
