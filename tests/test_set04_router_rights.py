"""SET-04: the chat's keyword router asks the rights table, and writes to the audit log.

When a message named containers, disks, storage or the network, the router called the read tools
directly. A person whose pages refuse them that data got it from Kib, and nothing was logged.
The table also gave everyone processor, memory, temperature and fan readings, which the stats
page keeps from kids and guests."""

import types

import pytest

from backend.services import ai_chat_agent as agent

KID = types.SimpleNamespace(scopes=["shares:read"], role_id="kid", username="kid", user_id="k1", id="k1")
OWNER = types.SimpleNamespace(scopes=["*"], role_id="superadmin", username="admin", user_id="a1", id="a1")

ASKS = [
    ("which containers are running?", "list_docker_containers", "tool_list_docker_containers"),
    ("are my disks asleep?", "get_disks_and_standby_status", "tool_get_disks_and_standby_status"),
    ("how much storage is free? pool status", "get_storage_status", "tool_get_storage_status"),
    ("what is my ip address", "get_network_status", "tool_get_network_status"),
    ("how busy is the cpu", "get_system_telemetry", "tool_get_system_telemetry"),
    ("what are the fans doing?", "get_fan_and_thermal_status", "tool_get_fan_and_thermal_status"),
]


@pytest.fixture
def turn(monkeypatch):
    """One chat turn with no model behind it; `ran` collects the tools that really ran."""
    ran, logged = [], []
    for _msg, name, func in ASKS:
        monkeypatch.setattr(agent, func, lambda *a, _n=name, **k: ran.append(_n) or {"tool": _n, "status": "ok"})
    monkeypatch.setattr(agent, "_try_local_llm_completion", lambda *a, **k: ("", "", 0, 0.0, {}, None))
    monkeypatch.setattr(agent, "detect_hardware_accelerator", lambda *a, **k: {"has_npu": False, "has_gpu": False})
    from backend import users_db

    monkeypatch.setattr(users_db, "log_security_event", lambda event, status, **k: logged.append((event, status, k)))

    def run(message, principal):
        return agent._run_agentic_chat_turn(message, [], False, True, None, principal)

    return run, ran, logged


@pytest.mark.parametrize("message, name, _func", ASKS)
def test_a_kid_gets_a_refusal_and_the_tool_does_not_run(turn, message, name, _func):
    run, ran, logged = turn
    out = run(message, KID)
    assert name not in ran
    refused = [r for r in out["tool_results"] if r.get("tool") == name]
    assert refused and refused[0]["status"] == "forbidden"
    assert any(e == "ai.tool.call" and s == "failure" and k["details"]["tool"] == name for e, s, k in logged)


@pytest.mark.parametrize("message, name, _func", ASKS)
def test_the_owner_gets_the_answer_and_it_is_logged(turn, message, name, _func):
    run, ran, logged = turn
    run(message, OWNER)
    assert name in ran
    entry = next(k for e, s, k in logged if e == "ai.tool.call" and k["details"]["tool"] == name)
    assert entry["details"]["source"] == "router" and entry["actor_username"] == "admin"


def test_who_are_you_carries_no_refusal_for_a_kid(turn):
    run, ran, _logged = turn
    out = run("who are you", KID)
    assert "get_system_telemetry" not in ran
    assert not any(r.get("status") == "forbidden" for r in out["tool_results"])


def test_the_table_matches_the_stats_page():
    for name in ("get_system_telemetry", "get_fan_and_thermal_status"):
        assert agent.TOOL_REQUIRED_SCOPES[name] == ("system:view", "hardware:read")
        assert not agent.TOOL_REGISTRY.allowed(name, KID)
        assert agent.TOOL_REGISTRY.allowed(name, OWNER)


def test_the_router_calls_no_read_tool_directly():
    import inspect

    src = inspect.getsource(agent._turn_run_requested_tools)
    for func in ("tool_list_docker_containers(", "tool_get_disks_and_standby_status(", "tool_get_storage_status("):
        assert func not in src
    for func in ("tool_get_network_status(", "tool_get_system_telemetry(", "tool_get_fan_and_thermal_status("):
        assert func not in src
