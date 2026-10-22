"""AI-05 / AI-06: AI data stays on the NAS unless the user turns web access on."""

from backend.services import ai_chat_agent, ai_endpoints


def test_router_is_never_a_candidate(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LLM_HOST", raising=False)
    monkeypatch.setattr(ai_endpoints, "_resolves", lambda name: False)
    monkeypatch.setattr(ai_endpoints, "_default_gateway", lambda: "192.168.1.1")
    hosts = ai_endpoints.candidate_hosts("192.168.1.50")
    assert "192.168.1.1" not in hosts
    assert hosts == ["192.168.1.50", "172.17.0.1", "127.0.0.1"]


def test_docker_bridge_gateway_and_named_containers_are_used(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LLM_HOST", raising=False)
    monkeypatch.setattr(ai_endpoints, "_resolves", lambda name: name == "zettnas-ollama")
    monkeypatch.setattr(ai_endpoints, "_default_gateway", lambda: "172.21.0.1")
    hosts = ai_endpoints.candidate_hosts(None)
    assert hosts[0] == "zettnas-ollama" and "172.21.0.1" in hosts


def test_explicit_host_wins(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.9:11434")
    assert ai_endpoints.candidate_hosts(None)[0] == "10.0.0.9"


def test_web_tools_refuse_without_permission(monkeypatch):
    called = []
    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", lambda *a, **k: called.append(a))
    res = ai_chat_agent.run_agentic_chat("what's the weather in Paris", [], False, True, None, None)
    assert not called
    assert res["external_services"] == [] and res["web_allowed"] is False
    token = ai_chat_agent._WEB_ALLOWED.set(False)
    try:
        assert ai_chat_agent.tool_browse_internet("news")["status"] == "blocked"
        assert ai_chat_agent.tool_get_weather("Paris")["status"] == "blocked"
    finally:
        ai_chat_agent._WEB_ALLOWED.reset(token)


def test_external_services_are_reported():
    out = ai_chat_agent._external_services(
        [
            {"tool": "get_weather", "status": "ok"},
            {"tool": "browse_internet", "status": "ok", "sources": [{"url": "https://en.wikipedia.org/wiki/X"}]},
            {"tool": "browse_internet", "status": "blocked"},
        ]
    )
    assert out == ["wttr.in (weather)", "web search", "en.wikipedia.org"]


def test_advisor_flags_published_ai_runtimes(monkeypatch):
    from backend.services import security_advisor

    containers = [
        {
            "Names": ["/zettnas-ollama"],
            "Image": "ollama/ollama",
            "Ports": [{"IP": "0.0.0.0", "PrivatePort": 11434, "PublicPort": 11434}],
        },
        {
            "Names": ["/safe-ovms"],
            "Image": "openvino/model_server",
            "Ports": [{"IP": "127.0.0.1", "PrivatePort": 8000, "PublicPort": 8000}],
        },
        {"Names": ["/web"], "Image": "nginx", "Ports": [{"IP": "0.0.0.0", "PrivatePort": 80, "PublicPort": 80}]},
    ]
    monkeypatch.setattr("backend.services.container_mutator._docker_request", lambda *a, **k: (200, containers))
    assert security_advisor.exposed_ai_runtimes() == ["zettnas-ollama:11434"]
