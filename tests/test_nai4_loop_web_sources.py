"""NAI-4: pages a web search found in the tool loop are the reply's sources too."""

import time

from backend.services import ai_chat_agent as agent

A = {"title": "A", "url": "https://a.example/x", "snippet": "a"}
B = {"title": "B", "url": "https://b.example/y", "snippet": "b"}


def test_loop_sources_are_added_once():
    web = [dict(A)]
    results = [
        {"tool": "browse_internet", "status": "ok", "sources": web},  # the router's own search
        {"tool": "browse_internet", "status": "ok", "sources": [A, B, {"title": "no url"}]},
        {"tool": "browse_internet", "status": "blocked", "sources": [{"url": "https://c.example"}]},
        {"tool": "search_nas_knowledge", "sources": [{"url": "https://d.example"}]},
    ]
    agent.loop_web_sources(results, web)
    assert [s["url"] for s in web] == ["https://a.example/x", "https://b.example/y"]


def test_the_turn_result_carries_them():
    web: list = []
    agent._turn_trace(
        act_accel={},
        active_model="m",
        cfg={},
        citations=[],
        eval_tokens=0,
        llm_reply="It is so [1].",
        measured_tok_sec=None,
        runtime_accel=None,
        runtime_name="test",
        t0=time.perf_counter(),
        tool_results=[{"tool": "browse_internet", "status": "ok", "sources": [B]}],
        tools_called=["browse_internet"],
        web_sources=web,
    )
    assert web == [B]
