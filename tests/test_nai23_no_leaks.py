"""NAI-2, NAI-3: nothing from the person's files leaves through weather or a web search they didn't ask for."""

from backend.services import ai_chat_agent as agent


def test_weather_only_for_a_place_the_person_named():
    assert agent.weather_place_ok("Paris", "what's the weather in paris tomorrow?")
    assert agent.weather_place_ok("", "weather?")
    assert not agent.weather_place_ok("IBAN DE89 3704 0044", "what's the weather?")
    assert not agent.weather_place_ok("Berlin", "weather in paris")


def test_asking_for_the_web():
    assert agent.asked_for_web("Search the web for the warranty of this TV")
    assert not agent.asked_for_web("what does my lease say about pets?")


def _call(name, **args):
    return {"function": {"name": name, "arguments": args}}


def test_the_loop_refuses_both(monkeypatch):
    ran = []
    rounds = [[_call("get_weather", location="secret account 1234"), _call("browse_internet", query="rent amount")]]

    def model(**kw):
        return ("ok", "fake", 1, 1.0, {}, rounds.pop(0) if rounds else [])

    monkeypatch.setattr(agent, "_try_local_llm_completion", model)
    monkeypatch.setattr(agent, "execute_nas_tool", lambda n, a, principal=None: ran.append(n) or {"tool": n})
    monkeypatch.setattr(agent, "tools_for_principal", lambda p, web: [{"name": "x"}])
    monkeypatch.setattr(agent, "_fit_to_window", lambda m, t, w: m)
    monkeypatch.setattr(agent, "_context_window_for", lambda: 8192)
    monkeypatch.setattr(agent, "model_web_query", lambda q, u, p: (q, False, ""))
    results = []
    agent._turn_call_model(
        active_model="m",
        allow_nas_tools=True,
        citations=[{"excerpt": "rent amount 900"}],
        is_pure_conversational=False,
        llm_endpoint="http://x",
        llm_messages=[{"role": "user", "content": "how much is my rent?"}],
        principal=None,
        tool_results=results,
        tools_called=[],
        user_text="how much is my rent?",
    )
    assert ran == []
    assert [r["status"] for r in results] == ["blocked", "blocked"]
