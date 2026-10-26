"""ARC-5: one chat turn behaves exactly as recorded while the 938-line function is split up.

Every tool that reads the machine or the network is replaced by data recorded once from the
real tools (tests/golden/chat_turn.json, "tools"); the calculator stays real. Each message
runs with the model unreachable (the built-in replies), with a fake model that answers, and
with one that first asks for a tool. The turn's whole result (timings aside) and what the
model was shown must match the recording. Regenerate only for an intended change:

    ZETTNAS_UPDATE_GOLDEN=1 pytest tests/test_arc5_chat_turn_characterization.py
"""

import copy
import json
import os
import types

import pytest

from backend.services import ai_chat_agent as agent

GOLDEN = os.path.join(os.path.dirname(__file__), "golden", "chat_turn.json")
ADMIN = types.SimpleNamespace(scopes=["*"], role="superadmin", username="admin", user_id="admin", id="admin")

TOOL_FUNCS = {
    "get_disks_and_standby_status": ("tool_get_disks_and_standby_status", (), {}),
    "get_fan_and_thermal_status": ("tool_get_fan_and_thermal_status", (), {}),
    "get_network_status": ("tool_get_network_status", (), {}),
    "get_storage_status": ("tool_get_storage_status", (), {}),
    "get_system_telemetry": ("tool_get_system_telemetry", (), {}),
    "list_docker_containers": ("tool_list_docker_containers", (), {}),
    "get_weather": ("tool_get_weather", ("Oslo",), {}),
    "browse_internet": ("tool_browse_internet", ("what is raid 5",), {}),
    "search_nas_knowledge": ("tool_search_nas_knowledge", ("tax documents",), {}),
}

WEATHER_HISTORY = [
    {"role": "user", "content": "what's the weather in Oslo"},
    {"role": "assistant", "content": "### Live Weather: Oslo\n- Temperature: 4°C"},
]
MESSAGES = [
    ("hi there", []),
    ("thanks!", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}]),
    ("what is 15% of 80", []),
    ("calculate (12 + 8) * 3", []),
    ("16 TB to TiB", []),
    ("what's the weather in Oslo", []),
    ("and tomorrow?", WEATHER_HISTORY),
    ("how much storage is free?", []),
    ("are my disks asleep?", []),
    ("how hot is it, and what are the fans doing?", []),
    ("which containers are running?", []),
    ("restart plex", []),
    ("what is my ip address", []),
    ("how busy is the cpu", []),
    ("who are you", []),
    ("which tools did you use for that?", [{"role": "user", "content": "free space?"}]),
    ("what is raid 5", []),
    ("find my tax documents", []),
    ("search the web for the latest zfs release", []),
    ("[react] tell me something", []),
]


def _normalise(value):
    if isinstance(value, dict):
        return {
            k: _normalise(v)
            for k, v in value.items()
            if not any(t in k for t in ("elapsed", "_ms", "tok_sec", "tokens_per", "duration"))
        }
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value


def _record_tools():
    out = {}
    for name, (func, args, kwargs) in TOOL_FUNCS.items():
        try:
            out[name] = json.loads(json.dumps(getattr(agent, func)(*args, **kwargs), default=str))
        except Exception as e:
            out[name] = {"tool": name, "status": "error", "error": type(e).__name__}
    return out


def _stub(monkeypatch, tools, mode, seen):
    for name, (func, _args, _kwargs) in TOOL_FUNCS.items():
        monkeypatch.setattr(agent, func, lambda *a, _n=name, **k: copy.deepcopy(tools[_n]))
    monkeypatch.setattr(
        agent,
        "execute_nas_tool",
        lambda name, args=None, principal=None, **k: copy.deepcopy(tools.get(name) or {"tool": name, "status": "ok"}),
    )
    monkeypatch.setattr(agent, "detect_hardware_accelerator", lambda *a, **k: {"has_npu": False, "has_gpu": False})
    monkeypatch.setattr(agent, "read_total_ram_bytes", lambda *a, **k: 16 * 1024**3)
    monkeypatch.setattr(
        agent,
        "resolve_model_runtime_accelerator",
        lambda *a, **k: {"has_npu": False, "has_gpu": False, "active_tier": 3, "device_label": "Host CPU"},
    )
    calls = {"n": 0}

    def fake_llm(active_model=None, llm_endpoint=None, messages=None, tools=None):
        calls["n"] += 1
        msgs = messages or []
        seen.append(
            {
                "roles": [m.get("role") for m in msgs],
                "user": next((m.get("content") for m in reversed(msgs) if m.get("role") == "user"), ""),
                "tools_offered": sorted(t.get("function", {}).get("name", "") for t in tools or []),
            }
        )
        if mode == "down":
            return "", "", 0, 0.0, {}, None
        if "[react]" in seen[-1]["user"] and calls["n"] == 1:
            return "", "fake", 5, 1.0, {}, [{"function": {"name": "get_storage_status", "arguments": "{}"}}]
        return f"Fake model reply #{calls['n']} with {len(msgs)} messages.", "fake", 12, 3.0, {}, None

    monkeypatch.setattr(agent, "_try_local_llm_completion", fake_llm)


def _run_all(monkeypatch, tools):
    results = {}
    for mode in ("down", "answers"):
        for web in (False, True):
            for msg, history in MESSAGES:
                seen = []
                with monkeypatch.context() as m:
                    _stub(m, tools, mode, seen)
                    out = agent._run_agentic_chat_turn(msg, copy.deepcopy(history), web, True, None, ADMIN)
                results[f"{mode}|web{int(web)}|{msg}"] = {"out": _normalise(out), "model_saw": seen}
    return json.loads(json.dumps(results, sort_keys=True, default=str))


def test_a_chat_turn_matches_the_recording(monkeypatch):
    if os.environ.get("ZETTNAS_UPDATE_GOLDEN") == "1":
        tools = _record_tools()
        golden = {"tools": tools, "turns": _run_all(monkeypatch, tools)}
        os.makedirs(os.path.dirname(GOLDEN), exist_ok=True)
        with open(GOLDEN, "w", encoding="utf-8") as fh:
            json.dump(golden, fh, indent=1, sort_keys=True)
            fh.write("\n")
        pytest.skip("golden file written")
    with open(GOLDEN, encoding="utf-8") as fh:
        golden = json.load(fh)
    got = _run_all(monkeypatch, golden["tools"])
    assert set(got) == set(golden["turns"])
    changed = [k for k in golden["turns"] if got[k] != golden["turns"][k]]
    assert not changed, f"the chat turn changed in {len(changed)} cases, e.g. {changed[:3]}"
    assert len(got) == 4 * len(MESSAGES)
