"""NAI-1: a stopped or broken AI pack never holds a search for minutes."""

from backend.services import ai_pack

URL = "http://zettnas-ai:8000/v3"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _setup(monkeypatch, ready_after=None):
    clock = Clock()
    started = []
    monkeypatch.setattr(ai_pack, "_RUNNING", {"at": -1e9, "value": False})
    monkeypatch.setattr(ai_pack, "_STARTED", {"at": -1e9})
    monkeypatch.setattr(ai_pack, "_NOT_READY", {"at": -1e9})
    monkeypatch.setattr(ai_pack, "_ours_running", lambda: (True, bool(started)))
    monkeypatch.setattr(ai_pack, "_docker", lambda m, p, **k: started.append(p) or (204, {}))
    monkeypatch.setattr(ai_pack, "models_ready", lambda: ready_after is not None and clock.t - 1000.0 >= ready_after)
    return clock, started


def test_a_search_waits_only_its_own_deadline(monkeypatch):
    clock, started = _setup(monkeypatch, ready_after=60)
    assert ai_pack.wake_for(URL, sleep=clock.sleep, clock=clock, wait=6.0) is False
    assert clock.t - 1000.0 <= 6.0 and started  # the pack was started for the next search
    assert ai_pack.warming(clock=clock)


def test_indexing_waits_for_the_warm_up(monkeypatch):
    clock, _ = _setup(monkeypatch, ready_after=30)
    assert ai_pack.wake_for(URL, sleep=clock.sleep, clock=clock) is True
    assert not ai_pack.warming(clock=clock)


def test_a_broken_pack_is_skipped_for_a_minute(monkeypatch):
    clock, _ = _setup(monkeypatch, ready_after=None)
    assert ai_pack.wake_for(URL, sleep=clock.sleep, clock=clock) is False  # indexing waited it out
    t = clock.t
    assert ai_pack.wake_for(URL, sleep=clock.sleep, clock=clock, wait=6.0) is False
    assert clock.t == t  # a search right after doesn't wait at all


def test_the_banner_says_warming_up(monkeypatch):
    from backend.services import rag_engine_search

    monkeypatch.setattr(ai_pack, "warming", lambda: True)
    assert "warming up" in rag_engine_search.degraded_text()
    monkeypatch.setattr(ai_pack, "warming", lambda: False)
    assert "didn't answer" in rag_engine_search.degraded_text()


def test_a_warming_pack_doesnt_trip_the_breaker():
    import inspect

    from backend.services import rag_embeddings

    src = inspect.getsource(rag_embeddings.compute_multimodal_query_embedding)
    assert "if res is None and not _pack_warming():" in src
