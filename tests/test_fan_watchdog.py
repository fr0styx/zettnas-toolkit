"""The host fan watchdog: the app beats while it controls the fans; when the beats stop without a
clean release, the watchdog puts the fans in their safe state, once per outage."""

import json

from backend import fan_watchdog as wd
from backend.services import fan_heartbeat


def test_beats_are_written_and_throttled(tmp_path, monkeypatch):
    path = tmp_path / "hb.json"
    monkeypatch.setenv("FAN_WATCHDOG_HEARTBEAT", str(path))
    monkeypatch.setattr(fan_heartbeat, "_last", 0.0)
    assert fan_heartbeat.beat(now=100.0)
    assert json.loads(path.read_text())["ts"] == 100.0
    fan_heartbeat.beat(now=102.0)  # within 5 s: not rewritten
    assert json.loads(path.read_text())["ts"] == 100.0
    fan_heartbeat.beat(released=True, now=102.5, force=True)
    data = json.loads(path.read_text())
    assert data["released"] is True and data["ts"] == 102.5
    (tmp_path / "afile").write_text("x")
    monkeypatch.setenv("FAN_WATCHDOG_HEARTBEAT", str(tmp_path / "afile" / "hb.json"))
    assert fan_heartbeat.beat(now=200.0) is False  # can't write: reported, never raised


def test_the_default_place_is_the_hosts_dev_shm(monkeypatch):
    monkeypatch.delenv("FAN_WATCHDOG_HEARTBEAT", raising=False)
    assert fan_heartbeat.heartbeat_path().endswith("/shm/zettnas-fan-heartbeat.json")


def test_when_to_step_in():
    assert wd.needs_release({"ts": 0, "released": False}, now=31, stale=30)
    assert not wd.needs_release({"ts": 0, "released": False}, now=29, stale=30)
    assert not wd.needs_release({"ts": 0, "released": True}, now=999, stale=30)  # a clean shutdown
    assert not wd.needs_release(None, now=999)  # the app never ran here
    assert not wd.needs_release({"ts": "soon"}, now=999)


def test_one_release_per_outage(tmp_path):
    """Checks every 20 s. The app beats at t=0, dies, comes back at t=60, dies again."""
    path = tmp_path / "hb.json"
    t = {"now": 0.0}
    last_beat = {0: 0, 20: 0, 40: 0, 60: 60, 80: 60, 100: 60, 120: 60}
    calls = []

    def write():
        path.write_text(json.dumps({"ts": last_beat.get(t["now"], 60), "released": False}))

    def sleep(_):
        t["now"] += 20
        write()

    write()
    out = wd.watch(
        str(path),
        release=lambda: calls.append(t["now"]) or True,
        sleep=sleep,
        clock=lambda: t["now"],
        rounds=7,
        log=lambda m: None,
    )
    # stale at t=40 -> safe state; beating again at t=60 re-arms; stale again at t=100 -> once more
    assert out == 2 and calls == [40.0, 100.0]


def test_a_missing_or_broken_heartbeat_is_ignored(tmp_path):
    assert wd.read_heartbeat(str(tmp_path / "none.json")) is None
    (tmp_path / "bad.json").write_text("{nope")
    assert wd.read_heartbeat(str(tmp_path / "bad.json")) is None
    (tmp_path / "list.json").write_text("[1]")
    assert wd.read_heartbeat(str(tmp_path / "list.json")) is None


def test_a_clean_release_tells_the_watchdog(monkeypatch, tmp_path):
    """failsafe_release_fans (shutdown) writes a released beat, so the watchdog stays idle."""
    from backend.hardware import fans

    seen = []
    monkeypatch.setattr(
        fan_heartbeat, "beat", lambda released=False, force=False, now=None: seen.append((released, force)) or True
    )
    fans._tell_watchdog_released()
    assert seen == [(True, True)]
    monkeypatch.setattr(fan_heartbeat, "beat", lambda **k: 1 / 0)
    fans._tell_watchdog_released()  # never raises


def test_the_watchdog_release_uses_the_apps_safe_state(monkeypatch):
    from backend.hardware import fans

    reasons = []
    monkeypatch.setattr(fans, "failsafe_release_fans", lambda reason="", lock=False: reasons.append(reason) or True)
    assert wd._release() is True and "watchdog" in reasons[0]


def test_main_prints_where_it_watches(monkeypatch, capsys):
    monkeypatch.setattr(wd, "watch", lambda path, log=None: 0)
    monkeypatch.setenv("FAN_WATCHDOG_HEARTBEAT", "/x/hb.json")
    wd.main()
    assert "/x/hb.json" in capsys.readouterr().out


def test_check_reports_without_touching_the_fans(monkeypatch, tmp_path, capsys):
    path = tmp_path / "hb.json"
    path.write_text(json.dumps({"ts": 0, "released": False}))
    monkeypatch.setenv("FAN_WATCHDOG_HEARTBEAT", str(path))
    monkeypatch.setattr(wd, "controller", lambda: "hwmon /x")
    wd.main(["--check"])
    out = capsys.readouterr().out
    assert "hwmon /x" in out and "released=False" in out


def test_controller_lookup(monkeypatch):
    from types import SimpleNamespace

    from backend.hardware import cpu, fans

    monkeypatch.setattr(cpu, "_find_hwmon", lambda: "/sys/class/hwmon/hwmon3")
    assert wd.controller() == "hwmon /sys/class/hwmon/hwmon3"
    monkeypatch.setattr(cpu, "_find_hwmon", lambda: None)
    monkeypatch.setattr(fans, "get_mmio_fan_controller", lambda: SimpleNamespace(is_available=lambda: True))
    assert "registers" in wd.controller()
    monkeypatch.setattr(fans, "get_mmio_fan_controller", lambda: None)
    assert wd.controller() == "none"


def test_dry_run_only_logs(monkeypatch, capsys):
    monkeypatch.setattr(wd, "DRY_RUN", True)
    assert wd._release() is True
    assert "dry run" in capsys.readouterr().out
