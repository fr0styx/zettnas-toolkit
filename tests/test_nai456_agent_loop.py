"""NAI-4, NAI-5, NAI-6: the agent loop keeps every result, runs a tool again with other arguments,
and offers no tools after reading files or the web."""

from backend.services import ai_chat_agent as agent


def _call(name, **args):
    return {"function": {"name": name, "arguments": args}}


def _run(monkeypatch, rounds, results, said="hi"):
    calls, ran = [], []

    def model(**kw):
        calls.append(kw.get("tools"))
        nxt = rounds.pop(0) if rounds else []
        return ("ok", "fake", 1, 1.0, {}, nxt)

    def tool(name, args, principal=None):
        ran.append((name, dict(args)))
        return dict(results.get(name, {"tool": name, "status": "ok"}), args=dict(args))

    monkeypatch.setattr(agent, "_try_local_llm_completion", model)
    monkeypatch.setattr(agent, "execute_nas_tool", tool)
    monkeypatch.setattr(agent, "tools_for_principal", lambda p, web: [{"name": "x"}])
    monkeypatch.setattr(agent, "_fit_to_window", lambda m, t, w: m)
    monkeypatch.setattr(agent, "_context_window_for", lambda: 8192)
    tool_results, tools_called = [], []
    agent._turn_call_model(
        active_model="m",
        allow_nas_tools=True,
        citations=[],
        is_pure_conversational=False,
        llm_endpoint="http://x",
        llm_messages=[{"role": "user", "content": "hi"}],
        principal=None,
        tool_results=tool_results,
        tools_called=tools_called,
        user_text=said,
    )
    return calls, ran, tool_results


def test_other_arguments_run_again_and_every_result_is_kept(monkeypatch):
    rounds = [
        [
            _call("get_weather", location="Paris"),
            _call("get_weather", location="Berlin"),
            _call("get_weather", location="Paris"),
        ]
    ]
    calls, ran, results = _run(monkeypatch, rounds, {}, said="weather in Paris and Berlin?")
    assert ran == [("get_weather", {"location": "Paris"}), ("get_weather", {"location": "Berlin"})]
    assert [r["args"]["location"] for r in results] == ["Paris", "Berlin"]


def test_a_container_action_reaches_the_trace(monkeypatch):
    rounds = [[_call("control_docker_container", container="immich", action="restart")]]
    _, _, results = _run(
        monkeypatch,
        rounds,
        {
            "control_docker_container": {
                "tool": "control_docker_container",
                "status": "confirmation_required",
                "action_id": "a1",
            }
        },
    )
    assert results and results[0]["action_id"] == "a1"


def test_no_tools_after_reading_files(monkeypatch):
    rounds = [[_call("search_nas_knowledge", query="lease")], [_call("get_weather", location="Paris")]]
    calls, ran, _ = _run(monkeypatch, rounds, {})
    assert calls[0] is not None and calls[1] is None  # the round after the file text has no tools
