"""SSE live-stats delta encoder and broadcaster resync."""

import asyncio
import copy
import json

from backend.services.broadcaster import StatsBroadcaster
from backend.services.stats_delta import StatsDeltaEncoder


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _container(cid, **kw):
    c = {
        "id": cid,
        "name": f"app-{cid}",
        "state": "running",
        "image": "nginx:latest",
        "ports": [{"host": 8080, "container": 80}],
        "status": "Up 3 hours",
        "cpu_pct": 1.0,
        "mem_used": 100,
        "mem_limit": 1000,
        "mem_pct": 10.0,
        "net_rx": 5,
        "net_tx": 7,
    }
    c.update(kw)
    return c


def _tick(**over):
    data = {
        "cpu": {"util": 5, "temp": 40},
        "mem": {"pct": 30},
        "npu": {"present": False},
        "events": [{"ts": 1, "msg": "boot"}],
        "docker": [_container("a"), _container("b")],
    }
    data.update(over)
    return data


def _merge(state, msg):
    """Mirror of frontend state.setStats merge, used to prove round-trips."""
    msg = dict(msg)
    fresh = msg.pop("events_new", None)
    if fresh is not None:
        ids = {e["id"] for e in fresh}
        merged = fresh + [e for e in state.get("events", []) if e["id"] not in ids]
        merged.sort(key=lambda e: (e.get("last_ts") or e["ts"], e["id"]), reverse=True)
        msg["events"] = merged[:100]
    tel = msg.pop("docker_tel", None)
    if tel and isinstance(state.get("docker"), list):
        msg["docker"] = [{**c, **tel[c["id"]]} if c["id"] in tel else c for c in state["docker"]]
    return {**state, **msg}


def test_first_tick_is_full():
    enc = StatsDeltaEncoder(clock=FakeClock())
    data = _tick()
    assert enc.encode(data) == data


def test_unchanged_keys_are_omitted():
    enc = StatsDeltaEncoder(clock=FakeClock())
    enc.encode(_tick())
    out = enc.encode(_tick(cpu={"util": 9, "temp": 40}))
    assert out == {"cpu": {"util": 9, "temp": 40}}


def test_identical_tick_sends_empty_message():
    enc = StatsDeltaEncoder(clock=FakeClock())
    enc.encode(_tick())
    assert enc.encode(_tick()) == {}


def test_container_telemetry_goes_in_compact_delta():
    enc = StatsDeltaEncoder(clock=FakeClock())
    enc.encode(_tick())
    out = enc.encode(_tick(docker=[_container("a", cpu_pct=4.5, mem_used=150), _container("b")]))
    assert "docker" not in out
    assert out["docker_tel"] == {"a": {"cpu_pct": 4.5, "mem_used": 150}}


def test_status_text_drift_is_telemetry_not_structure():
    enc = StatsDeltaEncoder(clock=FakeClock())
    enc.encode(_tick())
    out = enc.encode(_tick(docker=[_container("a", status="Up 4 hours"), _container("b")]))
    assert out == {"docker_tel": {"a": {"status": "Up 4 hours"}}}


def test_structural_changes_send_full_list():
    cases = [
        [_container("a", state="exited"), _container("b")],
        [_container("a")],
        [_container("b"), _container("a")],
        [_container("a"), _container("b"), _container("c")],
        [_container("a", ports=[]), _container("b")],
        [_container("a", name="renamed"), _container("b")],
    ]
    for docker in cases:
        enc = StatsDeltaEncoder(clock=FakeClock())
        enc.encode(_tick())
        out = enc.encode(_tick(docker=docker))
        assert out.get("docker") == docker
        assert "docker_tel" not in out


def test_keyframe_resends_everything():
    clock = FakeClock()
    enc = StatsDeltaEncoder(keyframe_secs=300, clock=clock)
    enc.encode(_tick())
    assert enc.encode(_tick()) == {}
    clock.t += 300
    assert enc.encode(_tick()) == _tick()
    assert enc.encode(_tick()) == {}


def test_merged_deltas_reproduce_every_tick():
    enc = StatsDeltaEncoder(clock=FakeClock())
    ticks = [
        _tick(),
        _tick(cpu={"util": 7, "temp": 41}),
        _tick(docker=[_container("a", cpu_pct=3.0), _container("b", net_rx=99)]),
        _tick(docker=[_container("a", cpu_pct=3.0, state="exited"), _container("b", net_rx=99)]),
        _tick(events=[{"ts": 2, "msg": "x"}, {"ts": 1, "msg": "boot"}]),
        _tick(docker=[_container("a", cpu_pct=3.0, state="exited"), _container("b", net_rx=120, status="Up 4h")]),
    ]
    state = {}
    for data in ticks:
        state = _merge(state, enc.encode(copy.deepcopy(data)))
        assert state == data


def test_delta_is_much_smaller_than_full_tick():
    enc = StatsDeltaEncoder(clock=FakeClock())
    docker = [_container(f"c{i}") for i in range(26)]
    enc.encode(_tick(docker=docker))
    moved = [_container(f"c{i}", cpu_pct=2.0 + i, mem_used=200 + i) for i in range(26)]
    full = len(json.dumps(_tick(docker=moved)))
    delta = len(json.dumps(enc.encode(_tick(docker=moved))))
    assert delta < full / 3


def test_full_queue_resyncs_with_snapshot_instead_of_dropping():
    async def run():
        b = StatsBroadcaster()
        b.broadcast({"cpu": 1, "mem": 2}, full_data={"cpu": 1, "mem": 2})
        q = await b.subscribe()
        assert json.loads(q.get_nowait()[len("data: ") :]) == {"cpu": 1, "mem": 2}
        for i in range(q.maxsize):
            q.put_nowait(f'data: {{"cpu": {i}}}\n\n')
        b._latest_full_data = {"cpu": 9, "mem": 3}
        b._deliver('data: {"cpu": 9}\n\n')
        assert q.qsize() == 1
        assert json.loads(q.get_nowait()[len("data: ") :]) == {"cpu": 9, "mem": 3}

    asyncio.run(run())


def _event(n, **over):
    return {
        "id": n,
        "ts": 1000 + n,
        "level": "info",
        "title": f"Entry {n}",
        "message": "something happened " * 3,
        **over,
    }


def test_only_new_and_changed_log_entries_are_sent():
    """SET-13: one new entry sent the whole list of up to 100 again."""
    clock = FakeClock()
    enc = StatsDeltaEncoder(clock=clock)
    events = [_event(n) for n in range(100, 0, -1)]
    state = enc.encode(_tick(events=events))
    assert len(state["events"]) == 100
    clock.t += 2
    assert "events" not in enc.encode(_tick(events=events)) and "events_new" not in enc.encode(_tick(events=events))

    # a new entry pushes the oldest out
    events = [_event(101), *events[:99]]
    msg = enc.encode(_tick(events=events))
    assert "events" not in msg and msg["events_new"] == [_event(101)]
    assert len(json.dumps(msg)) < len(json.dumps(events)) / 20  # the stream is not larger: far smaller
    state = _merge(state, msg)
    assert state["events"] == events

    # a repeat is counted on its entry, which becomes the newest
    again = _event(50, count=2, last_ts=5000)
    events = [again, *[e for e in events if e["id"] != 50]]
    msg = enc.encode(_tick(events=events))
    assert msg["events_new"] == [again]
    state = _merge(state, msg)
    assert state["events"] == events

    # the log was cleared: the list itself is sent
    msg = enc.encode(_tick(events=[]))
    assert msg["events"] == [] and "events_new" not in msg
    state = _merge(state, msg)
    msg = enc.encode(_tick(events=[_event(102)]))
    assert msg["events_new"] == [_event(102)]
    assert _merge(state, msg)["events"] == [_event(102)]

    # a keyframe carries the whole list, so a client can never drift for long
    clock.t += 301
    assert enc.encode(_tick(events=[_event(102)]))["events"] == [_event(102)]


def test_entries_without_an_id_are_sent_whole_as_before():
    enc = StatsDeltaEncoder(clock=FakeClock())
    enc.encode(_tick())
    assert "events" not in enc.encode(_tick())
    msg = enc.encode(_tick(events=[{"ts": 2, "msg": "again"}, {"ts": 1, "msg": "boot"}]))
    assert msg["events"][0]["msg"] == "again" and "events_new" not in msg
