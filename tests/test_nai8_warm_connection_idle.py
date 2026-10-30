"""NAI-8: the warm search connection counts idleness from its last search, and is closed (its
cache freed) after WARM_IDLE_SECS without one."""

import time

import pytest

from backend.services import rag_engine as re_mod
from backend.services.rag_engine import RagSearchEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(re_mod, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = RagSearchEngine(db_path=str(tmp_path / "rag_index.db"))
    yield eng
    eng.close()


def test_steady_use_keeps_the_same_connection(engine, monkeypatch):
    first = engine._search_conn()
    inner = first._conn
    first.close()
    # an hour of searches every few minutes: never reopened, whatever its age
    monkeypatch.setattr(re_mod.time, "time", lambda: time.monotonic() + 10 * 3600)
    again = engine._search_conn()
    assert again._conn is inner
    again.close()


def test_idle_closes_it_and_the_next_search_reopens(engine):
    warm = engine._warm
    first = engine._search_conn()
    inner = first._conn
    first.close()
    assert warm._timer is not None and warm._timer.daemon
    assert warm.close_if_idle(now=warm._used + 5) is False  # used a moment ago
    assert warm.close_if_idle(now=warm._used + re_mod.WARM_IDLE_SECS) is True
    assert warm._conn is None
    assert warm.close_if_idle(now=time.time() + 10**6) is False  # nothing to close
    again = engine._search_conn()
    assert again._conn is not inner
    again.close()


def test_a_lent_connection_is_never_closed_under_a_search(engine):
    warm = engine._warm
    lent = engine._search_conn()
    try:
        assert isinstance(lent, re_mod._LentConnection)
        assert warm.close_if_idle(now=time.time() + 10**6) is False
        assert lent.execute("SELECT 1").fetchone()[0] == 1
    finally:
        lent.close()


def test_close_stops_the_timer(engine):
    c = engine._search_conn()
    c.close()
    timer = engine._warm._timer
    engine._warm.close()
    timer.join(1)
    assert not timer.is_alive()
