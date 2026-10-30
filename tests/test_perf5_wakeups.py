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


def test_container_inspections_share_one_pool():
    from backend.hardware import docker_stats

    first = docker_stats._inspect_pool()
    assert docker_stats._inspect_pool() is first and first._max_workers == 4
    assert docker_stats._INSPECT_CACHE_TTL >= 600


def test_docker_telemetry_waits_once_between_rounds(monkeypatch):
    from backend.hardware import docker_stats as ds
    from backend.state import Z_STATE

    waits, sleeps = [], []
    clock = {"t": 1000.0}
    monkeypatch.setattr(ds.time, "time", lambda: clock["t"])
    monkeypatch.setattr(ds, "docker_sock", lambda: "/nonexistent.sock")
    monkeypatch.setattr(ds.os.path, "exists", lambda p: True)

    class FakeConn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a):
            pass

        def getresponse(self):
            import types

            return types.SimpleNamespace(status=200, read=lambda: b'[{"Id": "abc123456789xyz"}]')

        def close(self):
            pass

    monkeypatch.setattr(ds, "UnixHTTPConnection", FakeConn)
    monkeypatch.setattr(ds, "_fetch_container_telemetry", lambda cid: {"cpu": 1.0})
    monkeypatch.setattr(ds, "container_poll_interval", lambda: 30.0)

    class FakeEvent:
        def clear(self):
            pass

        def wait(self, timeout):
            waits.append(timeout)
            clock["t"] += timeout
            monkeypatch.setattr(Z_STATE, "shutting_down", True)
            return False

    monkeypatch.setattr(ds, "_DEMAND_WAKE", FakeEvent())
    monkeypatch.setattr(ds.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    ds._docker_telemetry_worker()
    assert waits == [30.0]  # one wait for the whole interval
    assert sleeps == []


def test_docker_telemetry_backs_off_with_one_sleep(monkeypatch):
    from backend.hardware import docker_stats as ds
    from backend.state import Z_STATE

    sleeps = []
    monkeypatch.setattr(ds, "docker_sock", lambda: "/nonexistent.sock")
    monkeypatch.setattr(ds.os.path, "exists", lambda p: False)

    def sleep(s):
        sleeps.append(s)
        monkeypatch.setattr(Z_STATE, "shutting_down", True)

    monkeypatch.setattr(ds.time, "sleep", sleep)
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    ds._docker_telemetry_worker()
    assert sleeps == [ds.BACKOFF_SECS]


import pytest  # noqa: E402


@pytest.mark.parametrize("answer", ["no containers", "error"])
def test_docker_telemetry_backoff_when_idle_or_failing(monkeypatch, answer):
    import types

    from backend.hardware import docker_stats as ds
    from backend.state import Z_STATE

    sleeps = []
    monkeypatch.setattr(ds, "docker_sock", lambda: "/nonexistent.sock")
    monkeypatch.setattr(ds.os.path, "exists", lambda p: True)

    class FakeConn:
        def __init__(self, *a, **k):
            if answer == "error":
                raise OSError("socket gone")

        def request(self, *a):
            pass

        def getresponse(self):
            return types.SimpleNamespace(status=200, read=lambda: b"[]")

        def close(self):
            pass

    def sleep(s):
        sleeps.append(s)
        monkeypatch.setattr(Z_STATE, "shutting_down", True)

    monkeypatch.setattr(ds, "UnixHTTPConnection", FakeConn)
    monkeypatch.setattr(ds.time, "sleep", sleep)
    monkeypatch.setattr(ds, "_wait_for_apps", lambda: sleep(ds.NO_APPS_SECS))
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    ds._docker_telemetry_worker()
    # no app running: a minute, or until someone opens Apps (NPERF-6); an error: the short backoff
    assert sleeps == [ds.NO_APPS_SECS if answer == "no containers" else ds.BACKOFF_SECS]
