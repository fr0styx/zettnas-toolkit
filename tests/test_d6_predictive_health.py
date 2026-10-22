"""D6: a disk predicted to fail shows as warn/crit on the desktop and the front LCD."""

import time

from backend.hardware import disks
from backend.state import Z_STATE


def test_predicted_risk_raises_the_disk_health(monkeypatch):
    monkeypatch.setattr(
        disks,
        "_discover_disks",
        lambda: [{"dev": "sdb", "role": "data"}, {"dev": "sdc", "role": "data"}, {"dev": "sdd", "role": "data"}],
    )
    now = time.time()
    for dev in ("sdb", "sdc", "sdd"):
        Z_STATE.cached_smart_data[dev] = (35, "ok")
        Z_STATE.cached_smart_time[dev] = now
    Z_STATE.cached_smart_data["sdd"] = (None, "standby")
    monkeypatch.setattr(
        Z_STATE,
        "disk_risk",
        {
            "sdb": {"risk": "high", "advice": "Reallocated sectors are growing. Plan a replacement."},
            "sdc": {"risk": "low", "advice": ""},
            "sdd": {"risk": "critical", "advice": "x"},
        },
    )
    out = {d["dev"]: d for d in disks.read_disk_temps_and_io()}
    assert out["sdb"]["health"] == "warn" and out["sdb"]["risk"] == "high"
    assert "replacement" in out["sdb"]["risk_advice"]
    assert out["sdc"]["health"] == "ok"
    assert out["sdd"]["health"] == "standby"  # a sleeping disk stays shown as sleeping
