"""AI-03: the selected model is never swapped for another one."""

import io
import json

from backend.services import ai_chat_agent


class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_missing_model_is_not_aliased_or_substituted(monkeypatch):
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.setenv("ZETTNAS_TEST_MODE", "0")
    monkeypatch.setattr(ai_chat_agent, "_get_docker_host_ips", lambda: ["10.9.9.9"])
    ai_chat_agent._ACTIVE_ENDPOINT_CACHE.clear()
    calls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        calls.append(url)
        if url.endswith("/api/tags") and "10.9.9.9:11434" in url:
            return _Resp(json.dumps({"models": [{"name": "qwen2.5:3b"}, {"name": "llama3.2:1b"}]}).encode())
        raise OSError("unreachable")

    monkeypatch.setattr(ai_chat_agent.urllib.request, "urlopen", fake_urlopen)
    reply = ai_chat_agent._try_local_llm_completion("qwen2.5:7b", "", [{"role": "user", "content": "hi"}])
    assert reply[0] is None
    assert not any("/api/copy" in u or "/api/chat" in u for u in calls if "10.9.9.9:11434" in u)
    assert "not installed" in ai_chat_agent._LAST_MODEL_PROBLEM["text"]
    text = ai_chat_agent._no_model_reply("qwen2.5:7b")
    assert "`qwen2.5:7b` is not installed" in text and ai_chat_agent._LAST_MODEL_PROBLEM["text"] == ""
