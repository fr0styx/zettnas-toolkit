"""NAI-12, NAI-13: MCP follows the AI switches and the log; apps can't take the GPU for minutes."""

from types import SimpleNamespace

from backend.api import mcp
from backend.services import ai_apps


def test_mcp_follows_the_role_switch_and_logs(monkeypatch):
    from backend.services import ai_access

    logged = []
    monkeypatch.setattr(ai_access, "log_request", lambda *a, **k: logged.append(a))
    monkeypatch.setattr(ai_access, "allowed", lambda p, feature="ask": feature != "search")
    out = mcp._call_tool(
        "search_nas_knowledge", {"query": "lease"}, SimpleNamespace(role_id="share_user"), "http://nas"
    )
    assert out["isError"] and "turned off" in out["content"][0]["text"]
    assert logged[-1][1:5] == ("mcp", "search_nas_knowledge", False, "off_for_role")
    monkeypatch.setattr(
        "backend.services.ai_chat_agent.execute_nas_tool", lambda n, a, **k: {"status": "ok", "value": 1}
    )
    out = mcp._call_tool("get_system_status", {}, SimpleNamespace(role_id="share_user"), "http://nas")
    assert not out["isError"] and logged[-1][1:5] == ("mcp", "get_system_status", False, "ok")


def test_app_requests_are_kept_small():
    body = ai_apps.chat_body({"messages": [{"role": "user", "content": "hi"}], "n": 5, "max_tokens": 100000}, "m")
    assert body["n"] == 1 and body["max_tokens"] == ai_apps.APP_MAX_TOKENS
    body = ai_apps.chat_body({"messages": [{"role": "user", "content": "hi"}], "max_completion_tokens": 200}, "m")
    assert body["max_completion_tokens"] == 200 and "max_tokens" not in body
    body = ai_apps.chat_body({"messages": [{"role": "user", "content": "hi"}], "max_tokens": "lots"}, "m")
    assert body["max_tokens"] == ai_apps.APP_MAX_TOKENS
