"""PERF-5: fewer wakeups while idle."""


def test_the_backlight_is_written_when_it_changes(monkeypatch, tmp_path):
    from backend.hardware import screen

    writes = []
    monkeypatch.setattr(screen, "set_fb_blank", lambda on: writes.append(("blank", on)) or True)
    monkeypatch.setattr(screen, "discover_backlight_dir", lambda: None)
    monkeypatch.setattr(screen, "_LAST_BRIGHTNESS", {"pct": None, "at": 0.0})
    screen.set_screen_brightness(40, now=100.0, cached=True)
    screen.set_screen_brightness(40, now=110.0, cached=True)  # same value, 10 s later: skipped
    assert len(writes) == 1
    screen.set_screen_brightness(40, now=170.0, cached=True)  # a minute on: written again
    screen.set_screen_brightness(60, now=171.0, cached=True)  # a change: written
    screen.set_screen_brightness(60, now=172.0)  # an explicit change always writes
    assert len(writes) == 4


def test_the_smart_poller_checks_trends_every_five_minutes(monkeypatch):
    from backend.services import stats_collector as sc
    from backend.state import Z_STATE

    clock = {"t": 0.0}
    calls = {"poll": 0, "velocity": 0}
    monkeypatch.setattr(sc, "poll_all_disks_smart", lambda force=False: calls.__setitem__("poll", calls["poll"] + 1))
    monkeypatch.setattr(sc, "read_ups_status", lambda force=False: {})
    monkeypatch.setattr(
        sc, "evaluate_smart_velocity_alerts", lambda: calls.__setitem__("velocity", calls["velocity"] + 1)
    )
    monkeypatch.setattr(sc.time, "monotonic", lambda: clock["t"])
    ticks = {"n": 0}

    def sleep(s):
        assert s == sc.SMART_POLL_TICK_SECS  # one long sleep per tick, no slices
        clock["t"] += s
        ticks["n"] += 1
        if ticks["n"] > 61:  # ten minutes and a bit
            monkeypatch.setattr(Z_STATE, "shutting_down", True)

    monkeypatch.setattr(sc.time, "sleep", sleep)
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    sc.smart_poller_daemon()
    # the start-up scan counts once; then every 10 s a poll, every 300 s the trends
    assert calls["poll"] >= 60 and 2 <= calls["velocity"] <= 3


def test_idle_intervals():
    from backend.services import button_listener, rag_engine_learning

    assert button_listener.BUTTON_POLL_SECS >= 0.25
    assert rag_engine_learning.SPINUP_WATCH_SECS >= 30


def test_docker_is_asked_less_often_when_nobody_watches(monkeypatch):
    from backend.hardware import docker_stats
    from backend.services.broadcaster import broadcaster

    monkeypatch.setattr(broadcaster, "get_subscriber_count", lambda: 0)
    assert docker_stats._docker_ttl() == docker_stats._DOCKER_IDLE_TTL
    monkeypatch.setattr(broadcaster, "get_subscriber_count", lambda: 2)
    assert docker_stats._docker_ttl() == docker_stats._DOCKER_CACHE_TTL
    monkeypatch.setattr(broadcaster, "get_subscriber_count", lambda: 1 / 0)
    assert docker_stats._docker_ttl() == docker_stats._DOCKER_CACHE_TTL
