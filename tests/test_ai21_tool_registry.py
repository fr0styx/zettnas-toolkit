"""AI-21: Ask Zetty's tools come from one registry with one permission policy."""

from types import SimpleNamespace

from backend.services import ai_chat_agent as agent
from backend.services.ai_actions import MUTATING_TOOLS


def test_every_tool_has_definition_handler_and_policy():
    names = [d["function"]["name"] for d in agent.OPENAI_TOOL_DEFINITIONS]
    assert sorted(names) == sorted(agent.TOOL_REGISTRY.names())
    assert set(names) == set(agent.TOOL_REQUIRED_SCOPES) == set(agent._TOOL_HANDLERS)
    for n in MUTATING_TOOLS:
        assert agent.TOOL_REGISTRY.get(n).mutating
        assert agent.TOOL_REGISTRY.get(n).scopes  # changing the system always needs a scope


def test_policy_filters_offers_and_calls():
    viewer = SimpleNamespace(role_id="share_user", scopes=["shares:read", "system:view"])
    offered = {d["function"]["name"] for d in agent.tools_for_principal(viewer, web_allowed=False)}
    assert "set_fan_profile" not in offered and "browse_internet" not in offered
    assert "search_nas_knowledge" in offered
    assert "browse_internet" in {d["function"]["name"] for d in agent.tools_for_principal(viewer, web_allowed=True)}
    out = agent.execute_nas_tool("set_fan_profile", {"profile": "quiet"}, principal=viewer, confirmed=True)
    assert out["status"] == "forbidden"
    assert agent.execute_nas_tool("rm_rf", {}, principal=None)["status"] == "forbidden"


def test_mutating_tool_returns_a_proposal_until_confirmed(monkeypatch):
    calls = []
    monkeypatch.setattr(agent, "tool_set_fan_profile", lambda prof, **k: calls.append(prof) or {"status": "ok"})
    admin = SimpleNamespace(role_id="superadmin", scopes=["*"], username="admin")
    first = agent.execute_nas_tool("set_fan_profile", {"profile": "quiet"}, principal=admin)
    assert calls == []
    assert first["status"] == "confirmation_required" and first["action_id"]
    agent.execute_nas_tool("set_fan_profile", {"profile": "quiet"}, principal=admin, confirmed=True)
    assert calls == ["quiet"]
