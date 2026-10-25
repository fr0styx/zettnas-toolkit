"""AI-12: chat replies stream from the model as they're generated, and Stop stops the model."""

import asyncio
import json
import threading

from backend.services import ai_chat_agent as agent


def _collect():
    out = []
    return out, (lambda kind, text: out.append((kind, text)))


def test_think_tags_split_across_chunks():
    out, sink = _collect()
    sp = agent._ThinkSplitter(sink)
    for piece in ("Hi <thi", "nk>pondering</th", "ink> there"):
        sp.feed(piece)
    sp.flush()
    tokens = "".join(t for k, t in out if k == "token")
    think = "".join(t for k, t in out if k == "think")
    assert tokens == "Hi  there" and think == "pondering"


def _lines(chunks):
    return [(json.dumps(c) + "\n").encode() for c in chunks]


def test_ollama_stream_is_forwarded_and_reassembled():
    out, sink = _collect()
    tok = agent._TOKEN_SINK.set(sink)
    try:
        data = agent._read_llm_stream(
            _lines(
                [
                    {"message": {"content": "Hel"}},
                    {"message": {"content": "lo"}},
                    {"done": True, "eval_count": 2, "eval_duration": 1_000_000_000},
                ]
            ),
            "ollama",
        )
    finally:
        agent._TOKEN_SINK.reset(tok)
    assert [t for k, t in out] == ["Hel", "lo"]
    assert data["message"]["content"] == "Hello" and data["eval_count"] == 2


def test_openai_stream_tool_calls_reset_streamed_text():
    out, sink = _collect()
    sse = [
        b'data: {"choices":[{"delta":{"content":"Let me check"}}]}\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"calculate","arguments":"{\\"expr"}}]}}]}\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"ession\\": \\"2+2\\"}"}}]}}]}\n',
        b'data: {"choices":[],"usage":{"completion_tokens":7}}\n',
        b"data: [DONE]\n",
    ]
    tok = agent._TOKEN_SINK.set(sink)
    try:
        data = agent._read_llm_stream(sse, "openai_compatible")
    finally:
        agent._TOKEN_SINK.reset(tok)
    call = data["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "calculate"
    assert json.loads(call["function"]["arguments"]) == {"expression": "2+2"}
    assert out[-1] == ("reset", "") and data["usage"]["completion_tokens"] == 7


def test_cancel_stops_reading():
    ev = threading.Event()
    ev.set()
    tok = agent._CANCEL_EVENT.set(ev)
    try:
        data = agent._read_llm_stream(_lines([{"message": {"content": "never"}}]), "ollama")
    finally:
        agent._CANCEL_EVENT.reset(tok)
    assert data["message"]["content"] == ""


def _fake_chat(seen):
    def run(message, history, allow_web, allow_tools, model, principal, focus_path=None):
        sink = agent._TOKEN_SINK.get()
        seen["cancel"] = agent._CANCEL_EVENT.get()
        for piece in ("Live ", "tokens"):
            sink("token", piece)
        return {"status": "ok", "reply": "Live tokens", "tools_called": [], "tool_results": []}

    return run


def test_stream_endpoint_forwards_live_tokens(monkeypatch):
    seen = {}
    monkeypatch.setattr(agent, "run_agentic_chat", _fake_chat(seen))

    async def go():
        return [e async for e in agent.stream_agentic_chat("hello")]

    events = asyncio.run(go())
    tokens = [json.loads(e.split("data: ", 1)[1])["token"] for e in events if e.startswith("event: token")]
    assert tokens == ["Live ", "tokens"]  # streamed pieces, no replay of the whole answer
    assert any(e.startswith("event: done") for e in events)


def test_disconnect_sets_cancel(monkeypatch):
    seen = {}
    started = threading.Event()
    release = threading.Event()

    def slow(*a):
        seen["cancel"] = agent._CANCEL_EVENT.get()
        agent._TOKEN_SINK.get()("token", "first")
        started.set()
        release.wait(2)
        return {"status": "ok", "reply": "x", "tools_called": [], "tool_results": []}

    monkeypatch.setattr(agent, "run_agentic_chat", slow)

    async def go():
        gen = agent.stream_agentic_chat("hello")
        first = await gen.__anext__()
        await gen.aclose()  # what Starlette does when the browser goes away
        release.set()
        return first

    first = asyncio.run(go())
    assert "first" in first and seen["cancel"].is_set()
