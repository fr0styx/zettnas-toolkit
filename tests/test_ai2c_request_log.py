"""\"Who asked Kib\" writes what happened (SET-15, AI 2)."""

import time

from backend.api import media
from backend.services import ai_access


def test_a_tool_result_becomes_a_log_word():
    assert ai_access.tool_outcome({"status": "ok"}) == "answered"
    assert ai_access.tool_outcome({"status": "confirmation_required"}) == "answered"
    assert ai_access.tool_outcome({"status": "error"}) == "failed"
    assert ai_access.tool_outcome({"status": "blocked"}) == "failed"
    assert ai_access.tool_outcome({"status": "forbidden"}) == "refused"
    assert ai_access.tool_outcome({}) == "answered"
    assert ai_access.tool_outcome(None) == "answered"


def test_a_stream_is_read_for_how_it_ended():
    assert media._stream_outcome('event: token\ndata: {"t": "x"}\n\n', "failed", "") == ("failed", "")
    assert media._stream_outcome('event: done\ndata: {"active_model": "qwen3:4b"}\n\n', "failed", "") == (
        "streamed",
        "qwen3:4b",
    )
    assert media._stream_outcome("event: done\ndata: not json\n\n", "failed", "m") == ("streamed", "m")
    assert media._stream_outcome('event: error\ndata: {"error": "x"}\n\n', "streamed", "m") == ("failed", "m")


def test_the_log_is_written_after_the_stream(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_access, "log_request", lambda *a: calls.append(a))

    async def gen():
        yield "event: token\ndata: {}\n\n"
        assert not calls  # nothing written before the answer
        yield 'event: done\ndata: {"active_model": "qwen3:4b"}\n\n'

    class Req:
        model = ""
        allow_web_search = True

    import asyncio

    async def run():
        return [c async for c in media._logged_stream(gen(), "p", Req(), time.monotonic())]

    assert len(asyncio.run(run())) == 2
    principal, kind, model, web, outcome, ms = calls[0]
    assert (kind, model, web, outcome) == ("chat", "qwen3:4b", True, "streamed")


def test_reading_the_log_drops_old_entries(monkeypatch):
    old = time.time() - (ai_access.LOG_DAYS + 2) * 86400
    ai_access.log_request(
        type("P", (), {"username": "ann", "role_id": "admin"})(), "chat", "m", False, "answered", now=old
    )
    ai_access._PRUNED["at"] = 0
    assert all(r.get("ts", time.time()) > old + 1 for r in ai_access.recent(500))
