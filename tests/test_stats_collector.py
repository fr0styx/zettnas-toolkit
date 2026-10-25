"""The stats loop: fan zones, zero-RPM, critical overrides, health alerts, LEDs and publishing."""

import time

import pytest

from backend.services import stats_collector as sc
from backend.state import Z_STATE


@pytest.fixture
def hw(monkeypatch):
    """Records what the loop would do to the hardware."""
    calls = {"zone": [], "set": [], "events": [], "notify": [], "led": [], "led_state": []}
    monkeypatch.setattr(sc, "detect_chassis_model", lambda: "d6u")
    monkeypatch.setattr(
        sc, "read_unraid_status", lambda: {"mover": {"active": False}, "parity_check": {"active": False}}
    )
    monkeypatch.setattr(
        sc,
        "apply_zone_pwm",
        lambda zone, pwm, hold_secs=0, allow_zero=False: (
            calls["zone"].append((zone, pwm, hold_secs, allow_zero)) or pwm
        ),
    )
    monkeypatch.setattr(sc, "set_fan_pwm", lambda profile, **kw: calls["set"].append((profile, kw)))
    monkeypatch.setattr(sc, "add_event", lambda level, title, msg, details=None: calls["events"].append((level, title)))
    monkeypatch.setattr(sc, "_async_notify", lambda **kw: calls["notify"].append(kw))
    monkeypatch.setattr(sc, "send_led_packet", lambda *a, **k: calls["led"].append(a))
    monkeypatch.setattr(sc, "apply_led_state", lambda cfg: calls["led_state"].append(cfg))
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: object())
    monkeypatch.setattr(Z_STATE, "fan_state_tracker", {})
    monkeypatch.setattr(Z_STATE, "critical_temp_active", False)
    return calls


def run(disks, cpu_temp=45, profile="auto", fan_cfg=None, **over):
    settings = sc._fan_settings()
    args = dict(
        cpu_hold_secs=10,
        cpu_temp=cpu_temp,
        ctrl_cpu_fan=over.pop("ctrl_cpu_fan", False),
        disk_hold_secs=30,
        disks=disks,
        fan_cfg=fan_cfg or {},
        profile=profile,
        temp_max=50,
        temp_min=37,
        zero_rpm_enabled=over.pop("zero_rpm_enabled", False),
        zero_rpm_nvme_ceiling=settings["zero_rpm_nvme_ceiling"],
        zero_rpm_stop_delay=over.pop("zero_rpm_stop_delay", 60),
        zero_rpm_stop_temp=over.pop("zero_rpm_stop_temp", 34),
    )
    return sc._run_fan_control(**args)


def hdd(dev, temp, bay=None, standby=False):
    return {"dev": dev, "name": dev, "role": "data", "temp": temp, "bay": bay, "standby": standby}


def nvme(dev, temp):
    return {"dev": dev, "name": "nv" + dev[-1], "role": "cache", "temp": temp, "is_nvme": True}


class TestFanSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.setattr(sc, "read_json_cached", lambda path, default, **kw: {})
        s = sc._fan_settings()
        assert s["profile"] == "auto" and s["temp_min"] == 37 and s["temp_max"] == 50

    def test_saved_values_win(self, monkeypatch):
        monkeypatch.setattr(
            sc,
            "read_json_cached",
            lambda path, default, **kw: {"profile": "quiet", "temp_max": 55, "cpu_hold_secs": "7"},
        )
        s = sc._fan_settings()
        assert s["profile"] == "quiet" and s["temp_max"] == 55 and s["cpu_hold_secs"] == 7

    def test_a_broken_file_falls_back(self, monkeypatch):
        monkeypatch.setattr(sc, "read_json_cached", lambda path, default, **kw: ["not", "a", "dict"])
        assert sc._fan_settings()["profile"] == "auto"


class TestFanControl:
    def test_no_disks_at_all(self, hw):
        """Regression: an empty machine used to crash the loop on every cycle."""
        r = run([])
        assert r["z1_all_standby"] and r["z2_all_standby"]
        assert hw["set"]

    def test_bays_split_into_zones(self, hw):
        r = run([hdd("sda", 41, bay=1), hdd("sdb", 35, bay=2), hdd("sdc", 47, bay=4), hdd("sdd", 30, bay=6)])
        assert r["t_zone1"] == 41 and r["t_zone2"] == 47

    def test_without_bay_numbers_disks_are_halved(self, hw):
        r = run([hdd("sda", 30), hdd("sdb", 31), hdd("sdc", 44), hdd("sdd", 45)])
        assert r["t_zone1"] == 31 and r["t_zone2"] == 45

    def test_d4_has_one_zone(self, hw, monkeypatch):
        monkeypatch.setattr(sc, "detect_chassis_model", lambda: "d4")
        r = run([hdd("sda", 30), hdd("sdb", 44)])
        assert r["t_zone1"] == 44 and r["t_zone2"] == 30  # zone 2 has no disks: default

    def test_sleeping_disks_do_not_count(self, hw):
        r = run([hdd("sda", 48, bay=1, standby=True), hdd("sdb", 33, bay=2)])
        assert r["t_zone1"] == 33

    def test_hot_nvme_ramps_both_zones(self, hw):
        cool = run([hdd("sda", 30, bay=1), hdd("sdb", 30, bay=5)])
        hw["zone"].clear()
        run([hdd("sda", 30, bay=1), hdd("sdb", 30, bay=5), nvme("nvme0", 70)])
        pwms = {z: p for z, p, *_ in hw["zone"]}
        assert pwms[1] > 95 and pwms[2] > 95 and cool["t_nvme"] is None

    def test_custom_nvme_curve(self, hw):
        curve = [[30, 20], [60, 100]]
        run([hdd("sda", 30, bay=1), nvme("nvme0", 60)], fan_cfg={"nvme_curve_points": curve})
        assert hw["zone"]

    @pytest.mark.parametrize("cpu_temp", [None, 85, 72, 60, 40])
    def test_cpu_fan_steps(self, hw, cpu_temp):
        run([hdd("sda", 30, bay=1)], cpu_temp=cpu_temp, ctrl_cpu_fan=True)
        assert any(z == 3 for z, *_ in hw["zone"])

    def test_cpu_curve(self, hw):
        run(
            [hdd("sda", 30, bay=1)], cpu_temp=60, ctrl_cpu_fan=True, fan_cfg={"cpu_curve_points": [[40, 20], [80, 100]]}
        )
        assert any(z == 3 for z, *_ in hw["zone"])

    def test_a_critical_disk_forces_full_speed(self, hw):
        run([hdd("sda", 70, bay=1)], ctrl_cpu_fan=True)
        assert all(p == sc.FAN_MAX_PWM for _, p, *_ in hw["zone"])
        assert ("error", "Critical Temperature Threshold Reached") in hw["events"]
        assert Z_STATE.critical_temp_active

    def test_a_critical_cpu_forces_full_speed_and_recovers(self, hw):
        run([hdd("sda", 30, bay=1)], cpu_temp=90)
        assert Z_STATE.critical_temp_active
        run([hdd("sda", 30, bay=1)], cpu_temp=45)
        assert not Z_STATE.critical_temp_active

    def test_zero_rpm_after_the_cooldown(self, hw, monkeypatch):
        disks = [hdd("sda", 28, bay=1, standby=True), hdd("sdb", 28, bay=5, standby=True)]
        first = run(disks, zero_rpm_enabled=True, zero_rpm_stop_delay=60)
        assert first["z1_eligible"] and first["z1_rem"] > 0  # cooling down
        # 20 seconds later (cool bays use a 15-second delay)
        real_time = time.time
        monkeypatch.setattr(sc.time, "time", lambda: real_time() + 20)
        hw["zone"].clear()
        run(disks, zero_rpm_enabled=True, zero_rpm_stop_delay=60)
        assert (1, 0, 0, True) in hw["zone"] and (2, 0, 0, True) in hw["zone"]

    def test_storage_work_blocks_zero_rpm(self, hw, monkeypatch):
        monkeypatch.setattr(sc, "read_unraid_status", lambda: {"mover": {"active": True}, "parity_check": {}})
        r = run([hdd("sda", 28, bay=1, standby=True)], zero_rpm_enabled=True)
        assert r["storage_busy"] and not r["z1_eligible"]

    def test_unreadable_nvme_blocks_zero_rpm(self, hw):
        r = run(
            [hdd("sda", 28, bay=1, standby=True), {"dev": "nvme0", "role": "cache", "temp": None}],
            zero_rpm_enabled=True,
        )
        assert r["nvme_over_ceiling"] and not r["z1_eligible"]

    @pytest.mark.parametrize("profile", ["quiet", "balanced", "performance", "full", "manual"])
    def test_manual_profiles(self, hw, profile):
        run([hdd("sda", 30, bay=1)], profile=profile, ctrl_cpu_fan=True, fan_cfg={"manual_pct": 50})
        assert hw["set"][-1][0] == profile
        assert all(sc.FAN_MIN_PWM <= p <= sc.FAN_MAX_PWM for _, p, *_ in hw["zone"])


class TestHealth:
    @pytest.fixture(autouse=True)
    def _cfg(self, monkeypatch):
        monkeypatch.setattr(sc, "read_json_cached", lambda path, default, **kw: {"cpu_temp_threshold": 85})
        monkeypatch.setattr(Z_STATE, "known_active_fans", {0, 1, 2})

    def test_quiet_when_all_is_well(self, hw):
        r = sc._check_health([], 45, False, [900, 900, 900], False, time.time())
        assert r == {"is_crit": False, "is_warn": False} and not hw["notify"]

    def test_a_stalled_fan_is_critical(self, hw):
        Z_STATE.fan_state_tracker["pwm1"] = {"current": 120, "last_spinup_time": 0.0}
        r = sc._check_health([], 45, False, [0, 900, 900], False, time.time())
        assert r["is_crit"] and hw["notify"][0]["dedup_key"] == "fan_stall"

    def test_zero_rpm_and_spin_up_are_not_stalls(self, hw):
        now = time.time()
        Z_STATE.fan_state_tracker["pwm1"] = {"current": 0}
        Z_STATE.fan_state_tracker["pwm2"] = {"current": 120, "last_spinup_time": now}
        assert not sc._check_health([], 45, False, [0, 0, 900], False, now)["is_crit"]

    def test_cpu_fan_ignored_when_not_controlled(self, hw):
        sc._check_health([], 45, False, [900, 900, 0], False, time.time())
        assert 2 not in Z_STATE.known_active_fans

    @pytest.mark.parametrize("temp, level", [(90, "critical"), (78, "warning")])
    def test_cpu_temperature(self, hw, temp, level):
        r = sc._check_health([], temp, False, [], False, time.time())
        assert hw["notify"][0]["level"] == level
        assert r["is_crit"] == (level == "critical") and r["is_warn"]

    def test_no_cpu_sensor(self, hw):
        assert sc._check_health([], None, False, [], False, time.time()) == {"is_crit": False, "is_warn": False}

    def test_drive_alerts(self, hw):
        bad = [{"name": "sda", "health": "crit", "temp": 60}, {"name": "sdb", "health": "warn", "temp": 50}]
        r = sc._check_health(bad, 40, False, [], True, time.time())
        keys = [n["dedup_key"] for n in hw["notify"]]
        assert keys == ["drive_crit_sda", "drive_warn_sdb"] and r["is_crit"] and r["is_warn"]


class TestLeds:
    @pytest.fixture(autouse=True)
    def _night(self, monkeypatch):
        monkeypatch.setattr(sc, "is_in_time_window", lambda a, b: False)
        monkeypatch.setattr(Z_STATE, "alert_active", False)
        monkeypatch.setattr(Z_STATE, "copy_active", False)

    def cfg(self, monkeypatch, **cfg):
        monkeypatch.setattr(sc, "read_json_cached", lambda path, default, **kw: cfg)

    def test_critical_is_red(self, hw, monkeypatch):
        self.cfg(monkeypatch)
        sc._update_leds(True, False)
        assert hw["led"][-1][:4] == (5, 255, 0, 0) and Z_STATE.alert_active

    @pytest.mark.parametrize("status, mode", [("copying", 2), ("success", 1), ("error", 5)])
    def test_copy_progress(self, hw, monkeypatch, status, mode):
        self.cfg(monkeypatch)
        monkeypatch.setattr(Z_STATE, "copy_active", True)
        monkeypatch.setattr(Z_STATE, "copy_status", status)
        sc._update_leds(False, False)
        assert hw["led"][-1][0] == mode

    def test_warning_is_amber_then_back_to_normal(self, hw, monkeypatch):
        self.cfg(monkeypatch)
        sc._update_leds(False, True)
        assert hw["led"][-1][:3] == (1, 255, 120)
        sc._update_leds(False, False)
        assert hw["led_state"] and not Z_STATE.alert_active

    def test_night_mode_turns_the_bar_off(self, hw, monkeypatch):
        self.cfg(monkeypatch, night_mode=True)
        monkeypatch.setattr(sc, "is_in_time_window", lambda a, b: True)
        sc._update_leds(False, False)
        assert hw["led"][-1] == (0, 0, 0, 0, 0, 0, 0, 0)
        monkeypatch.setattr(sc, "is_in_time_window", lambda a, b: False)
        sc._update_leds(False, False)
        assert hw["led_state"]  # restored after the night

    def test_not_reactive(self, hw, monkeypatch):
        self.cfg(monkeypatch, reactive=False, night_mode=True)
        monkeypatch.setattr(sc, "is_in_time_window", lambda a, b: True)
        sc._update_leds(True, True)
        assert hw["led"] == [(0, 0, 0, 0, 0, 0, 0, 0)]


class TestPublish:
    @pytest.fixture
    def pub(self, monkeypatch):
        sent, logged = [], []
        monkeypatch.setattr(sc, "evaluate_system_alerts", lambda unraid, ups: None)
        monkeypatch.setattr(sc.broadcaster, "broadcast", lambda payload, full_data=None: sent.append(payload))
        monkeypatch.setattr(sc, "log_metrics", lambda *a, **k: logged.append(a))
        monkeypatch.setattr("backend.services.ups_watchdog.check_ups_power_watchdog", lambda ups, now: None)
        return sent, logged

    def data(self):
        return {"unraid": {}, "ups": {}, "cpu": {"temp": 40, "util": 5}, "mem": {"pct": 10}, "name": "x"}

    def test_caches_broadcasts_and_wakes_the_lcd(self, pub, monkeypatch):
        sent, logged = pub
        monkeypatch.setattr(sc.stats_collector_daemon, "last_log", 0, raising=False)
        Z_STATE.lcd_wake.clear()
        sc._publish(self.data(), [], [], {"rx_bytes_sec": 1.0}, time.time())
        assert Z_STATE.cached_stats["name"] == "x" and sent and Z_STATE.lcd_wake.is_set()
        assert len(logged) == 1
        sc._publish(self.data(), [], [], {}, time.time())
        assert len(logged) == 1  # metrics are logged every 5 minutes


class TestLoop:
    def test_one_cycle_end_to_end(self, hw, monkeypatch):
        """The whole loop runs once on a machine without disks, fans or sensors."""
        published = []
        monkeypatch.setattr(sc, "read_disk_temps_and_io", lambda: [])
        monkeypatch.setattr(sc, "read_network_rates", lambda: {"rx_bytes_sec": 0, "tx_bytes_sec": 0})
        monkeypatch.setattr(sc, "read_cpu_temp", lambda: None)
        monkeypatch.setattr(sc, "read_fans", lambda: [])
        monkeypatch.setattr(sc, "get_effective_brightness", lambda: 50)
        monkeypatch.setattr(sc, "set_screen_brightness", lambda v, **kw: None)
        monkeypatch.setattr(sc, "_publish", lambda data, *a: published.append(data))
        monkeypatch.setattr(Z_STATE, "lcd_cycle_seconds", 1)
        monkeypatch.setattr(Z_STATE, "last_lcd_cycle_time", 0)
        monkeypatch.setattr(Z_STATE, "shutting_down", False)

        def stop(timeout=None):
            Z_STATE.shutting_down = True
            return True

        monkeypatch.setattr(Z_STATE.ui_wake, "wait", stop)
        sc.stats_collector_daemon()
        assert published and published[0]["status"] == "0 OK"


class TestCollect:
    def test_before_the_first_cycle(self, monkeypatch):
        monkeypatch.setattr(Z_STATE, "cached_stats", None)
        monkeypatch.setattr(sc, "read_unraid_status", lambda: {"available": False})
        data = sc.collect()
        assert data["status"] == "-- OK" and "events" in data and "lcd" in data

    def test_after_a_cycle(self, monkeypatch):
        monkeypatch.setattr(Z_STATE, "cached_stats", {"status": "3 OK"})
        monkeypatch.setattr(sc, "read_unraid_status", lambda: {"available": False})
        data = sc.collect()
        assert data["status"] == "3 OK" and data["unraid"] == {"available": False}


class TestSmartVelocity:
    @pytest.fixture
    def velo(self, monkeypatch):
        sent = []
        monkeypatch.setattr("backend.hardware.disks._discover_disks", lambda: [{"dev": "sda"}, {"dev": "sdb"}, {}])
        monkeypatch.setattr("backend.services.notifications.send_notification", lambda payload: sent.append(payload))
        monkeypatch.setattr("backend.state.add_event", lambda *a, **k: None)
        monkeypatch.setattr(sc, "_SMART_VELOCITY_LAST_ALERT", {})
        return sent

    def test_alerts_once_a_day_per_drive(self, velo, monkeypatch):
        values = {"sda": {"realloc_7d_delta": 3, "failure_risk": "high"}, "sdb": {"realloc_7d_delta": 0}}
        monkeypatch.setattr("backend.db.query_smart_velocity", lambda dev: values[dev])
        first = sc.evaluate_smart_velocity_alerts()
        assert [a["dev"] for a in first] == ["sda"] and len(velo) == 1
        assert sc.evaluate_smart_velocity_alerts() == []  # deduplicated
        assert Z_STATE.disk_risk["sdb"]["risk"] == "low"

    def test_errors_are_contained(self, velo, monkeypatch):
        def boom(dev):
            raise RuntimeError("db gone")

        monkeypatch.setattr("backend.db.query_smart_velocity", boom)
        assert sc.evaluate_smart_velocity_alerts() == []


def test_smart_poller_runs_a_cycle(monkeypatch):
    calls = []
    monkeypatch.setattr(sc, "poll_all_disks_smart", lambda force=False: calls.append(("smart", force)))
    monkeypatch.setattr(sc, "read_ups_status", lambda force=False: calls.append(("ups", force)))
    monkeypatch.setattr(sc, "evaluate_smart_velocity_alerts", lambda: calls.append(("velocity",)))
    monkeypatch.setattr("backend.hardware.disks.check_active_smart_tests", lambda: calls.append(("tests",)))
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) > 8:
            Z_STATE.shutting_down = True

    monkeypatch.setattr(sc.time, "sleep", fake_sleep)
    sc.smart_poller_daemon()
    assert ("smart", True) in calls and ("smart", False) in calls and ("tests",) in calls


def test_notifications_go_to_a_worker(monkeypatch):
    seen = []

    class Pool:
        def submit(self, fn, **kw):
            seen.append(kw)

    monkeypatch.setattr(sc, "_notify_executor", Pool())
    sc._async_notify(title="t")
    assert seen == [{"title": "t"}]

    class Broken:
        def submit(self, fn, **kw):
            raise RuntimeError("shut down")

    monkeypatch.setattr(sc, "_notify_executor", Broken())
    sc._async_notify(title="t")  # logged, not raised
