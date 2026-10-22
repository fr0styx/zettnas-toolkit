"""D1: MCP server over the tool registry; changes need a person to confirm; everything is audited."""

from backend.services import ai_actions
from backend.services import ai_chat_agent as agent


def _rpc(client, headers, method, params=None, req_id=1):
    body = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
    r = client.post("/api/mcp", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_initialize_and_list_tools(client, auth_headers):
    init = _rpc(client, auth_headers, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["capabilities"]["tools"] is not None
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=auth_headers)
    assert r.status_code == 202
    tools = {t["name"]: t for t in _rpc(client, auth_headers, "tools/list")["result"]["tools"]}
    assert "get_system_telemetry" in tools and "browse_internet" not in tools  # never web tools over MCP
    assert tools["set_fan_profile"]["annotations"]["readOnlyHint"] is False
    assert "inputSchema" in tools["calculate"]


def test_changes_return_a_confirm_link_and_never_run(client, auth_headers, monkeypatch):
    ai_actions._reset_for_tests()
    calls = []
    monkeypatch.setattr(agent, "tool_set_fan_profile", lambda *a, **k: calls.append(a) or {"status": "ok"})
    res = _rpc(client, auth_headers, "tools/call", {"name": "set_fan_profile", "arguments": {"profile": "quiet"}})
    text = res["result"]["content"][0]["text"]
    assert "confirm-action=" in text and calls == []
    action_id = text.split("confirm-action=")[1].split()[0]
    pending = client.get(f"/api/ai/actions/{action_id}", headers=auth_headers).json()
    assert "quiet" in pending["summary"]
    assert client.post(f"/api/ai/actions/{action_id}/confirm", headers=auth_headers).status_code == 200
    assert calls  # ran only after the person confirmed


def test_read_tools_run_and_are_audited(client, auth_headers, monkeypatch):
    seen = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda *a, **k: seen.append((a, k)))
    res = _rpc(client, auth_headers, "tools/call", {"name": "calculate", "arguments": {"expression": "6*7"}})
    assert "42" in res["result"]["content"][0]["text"]
    assert any(a[0] == "ai.tool.call" and k["details"]["source"] == "mcp" for a, k in seen)
    bad = _rpc(client, auth_headers, "tools/call", {"name": "rm_rf", "arguments": {}})
    assert bad["error"]["code"] == -32602
    assert _rpc(client, auth_headers, "nope")["error"]["code"] == -32601


def test_requires_authentication(client):
    r = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 401
