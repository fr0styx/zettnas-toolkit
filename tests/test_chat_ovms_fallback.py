"""Chat on an OpenVINO Model Server with Ollama as the fallback: no thinking pass, tools when the
server takes them, a fallback model when the server can't answer, and room for long answers."""

import io
import json
import urllib.error

import pytest

from backend.services import ai_chat_agent
from backend.services.chat_context import EndpointRegistry

OVMS = "http://zettnas-ovms:8000/v1"
TOOLS = [{"type": "function", "function": {"name": "restart_container", "parameters": {"type": "object"}}}]


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json(obj):
    return _Resp(json.dumps(obj).encode())


@pytest.fixture
def net(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(ai_chat_agent, "_get_docker_host_ips", lambda: ["10.9.9.9"])
    monkeypatch.setattr(ai_chat_agent, "_ENDPOINT_REGISTRY", EndpointRegistry())
    ai_chat_agent._ACTIVE_ENDPOINT_CACHE.clear()
    state = {"ovms_up": True, "ovms_tools": True, "bodies": [], "timeouts": []}

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        body = json.loads(req.data) if getattr(req, "data", None) else None
        if "zettnas-ovms" in url:
            if not state["ovms_up"]:
                raise urllib.error.URLError("connection refused")
            if url.endswith("/models"):
                return _json({"data": [{"id": "Qwen3-4B", "owned_by": "OVMS"}]})
            state["bodies"].append(body)
            state["timeouts"].append(timeout)
            if body.get("tools") and not state["ovms_tools"]:
                raise urllib.error.HTTPError(url, 400, "tools not supported", {}, io.BytesIO(b"{}"))
            msg = {"content": "Keep a copy elsewhere."}
            if body.get("tools"):
                msg = {
                    "content": "",
                    "tool_calls": [
                        {"id": "1", "type": "function", "function": {"name": "restart_container", "arguments": "{}"}}
                    ],
                }
            return _json({"model": "Qwen3-4B", "choices": [{"message": msg}], "usage": {"completion_tokens": 6}})
        if "10.9.9.9:11434" in url:
            if url.endswith("/api/tags"):
                return _json({"models": [{"name": "llama3.2:3b-instruct-q4_K_M"}]})
            if url.endswith("/api/ps"):
                return _json({"models": [{"size_vram": 1}]})
            if url.endswith("/api/chat"):
                state["bodies"].append(body)
                return _json(
                    {"message": {"content": "Fallback answer."}, "eval_count": 3, "eval_duration": 1_000_000_000}
                )
        raise OSError("unreachable " + url)

    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", urlopen)
    return state


def _ask(tools=None, fallback="llama3.2:3b-instruct-q4_K_M"):
    return ai_chat_agent._try_local_llm_completion(
        "Qwen3-4B", OVMS, [{"role": "user", "content": "hi"}], tools=tools, fallback_model=fallback
    )


def test_openvino_answers_without_thinking_and_with_room_for_long_answers(net):
    reply = _ask()
    assert reply[0] == "Keep a copy elsewhere." and reply[1].startswith("OpenVINO Model Server")
    assert net["bodies"][0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert net["timeouts"][0] == 180.0  # not streaming: the whole answer arrives at once


def test_tools_go_to_openvino(net):
    reply = _ask(tools=TOOLS)
    assert net["bodies"][0]["tools"] == TOOLS and reply[5][0]["function"]["name"] == "restart_container"


def test_a_server_without_tool_support_is_asked_again_without_tools(net):
    net["ovms_tools"] = False
    reply = _ask(tools=TOOLS)
    assert reply[0] == "Keep a copy elsewhere."
    assert "tools" in net["bodies"][0] and "tools" not in net["bodies"][1]


def test_ollama_answers_with_the_fallback_when_openvino_is_down(net):
    net["ovms_up"] = False
    reply = _ask()
    assert reply[0] == "Fallback answer." and reply[1] == "Ollama (llama3.2:3b-instruct-q4_K_M)"
    assert net["bodies"][-1]["model"] == "llama3.2:3b-instruct-q4_K_M"


def test_without_a_fallback_nothing_answers_under_another_name(net):
    net["ovms_up"] = False
    reply = _ask(fallback="")
    assert reply[0] is None and "not installed" in ai_chat_agent._LAST_MODEL_PROBLEM["text"]


def test_fallback_comes_from_the_settings(net, monkeypatch):
    from backend.services import rag_engine

    monkeypatch.setattr(
        rag_engine.get_rag_engine(), "get_config", lambda: {"llm_fallback_model": "llama3.2:3b-instruct-q4_K_M"}
    )
    net["ovms_up"] = False
    reply = ai_chat_agent._try_local_llm_completion("Qwen3-4B", OVMS, [{"role": "user", "content": "hi"}])
    assert reply[0] == "Fallback answer."


def test_the_setting_is_accepted(client, auth_headers, monkeypatch):
    from backend.services import rag_engine

    saved = {}
    monkeypatch.setattr(rag_engine.get_rag_engine(), "update_config", lambda u: saved.update(u) or u)
    r = client.put("/api/ai/config", json={"llm_fallback_model": "llama3.2:3b"}, headers=auth_headers)
    assert r.status_code == 200 and saved == {"llm_fallback_model": "llama3.2:3b"}
