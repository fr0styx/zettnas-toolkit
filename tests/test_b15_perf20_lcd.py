"""B15 PERF-20/6: a blanked LCD sleeps through stats samples, the old LCD_FPS=10 default is
dropped on update, and nobody listening means no delta encoding."""

import threading
import time
from types import SimpleNamespace

import pytest

from backend.services import lcd_pil, self_updater
from backend.services import stats_collector as sc
from backend.state import Z_STATE


def test_the_old_lcd_fps_default_is_dropped_on_update_and_other_values_kept():
    inspect = {"Id": "abc", "Config": {"Env": ["LCD_FPS=10", "TZ=UTC"]}, "HostConfig": {}}
    body, _ = self_updater.build_recreate_plan(inspect, {"Env": []}, "img")
    assert body["Env"] == ["TZ=UTC"]
    inspect["Config"]["Env"] = ["LCD_FPS=8"]
    body, _ = self_updater.build_recreate_plan(inspect, {"Env": []}, "img")
    assert body["Env"] == ["LCD_FPS=8"]


def test_the_pil_loop_says_when_it_is_blanked():
    state = SimpleNamespace(shutting_down=False, lcd_wake=threading.Event(), lcd_blanked=False)

    def screen_off(fb, blanked):
        state.shutting_down = True  # one round
        return True

    lcd_pil.run_loop(object(), 0.01, screen_off, state)
    assert state.lcd_blanked is True


@pytest.fixture
def pub(monkeypatch):
    sent = []
    monkeypatch.setattr(sc, "evaluate_system_alerts", lambda unraid, ups: None)
    monkeypatch.setattr(sc, "log_metrics", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.ups_watchdog.check_ups_power_watchdog", lambda ups, now: None)
    monkeypatch.setattr(sc.broadcaster, "broadcast", lambda payload, full_data=None: sent.append(payload))
    monkeypatch.setattr(sc.stats_collector_daemon, "last_log", time.time(), raising=False)
    return sent


def _data(n):
    return {"unraid": {}, "ups": {}, "cpu": {"temp": n}, "mem": {"pct": 1}}


def test_a_blanked_lcd_is_not_woken_by_stats(pub, monkeypatch):
    monkeypatch.setattr(Z_STATE, "lcd_blanked", True, raising=False)
    Z_STATE.lcd_wake.clear()
    sc._publish(_data(40), [], [], {}, time.time())
    assert not Z_STATE.lcd_wake.is_set()
    assert Z_STATE.cached_stats["cpu"] == {"temp": 40}  # the numbers are still kept
    monkeypatch.setattr(Z_STATE, "lcd_blanked", False)
    sc._publish(_data(41), [], [], {}, time.time())
    assert Z_STATE.lcd_wake.is_set()


def test_nobody_listening_skips_the_delta_and_a_listener_gets_everything(pub, monkeypatch):
    monkeypatch.setattr(Z_STATE, "lcd_blanked", False, raising=False)
    monkeypatch.setattr(sc.broadcaster, "get_subscriber_count", lambda: 0)
    sc._publish(_data(40), [], [], {}, time.time())
    assert pub[-1] == _data(40)
    monkeypatch.setattr(sc.broadcaster, "get_subscriber_count", lambda: 1)
    sc._publish(_data(40), [], [], {}, time.time())
    assert pub[-1] == _data(40)  # the encoder started over: a full message, not an empty delta
    sc._publish(_data(41), [], [], {}, time.time())
    assert pub[-1] == {"cpu": {"temp": 41}}
