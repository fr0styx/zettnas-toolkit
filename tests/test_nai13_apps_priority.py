"""NAI-13 (rest): apps wait behind the family's chats and searches, and each app key runs one
request at a time."""

import threading

import pytest

from backend.services import ai_apps
from backend.services import gpu_queue as gq


def test_apps_come_after_chat_and_search_and_before_indexing():
    assert gq.CHAT < gq.QUERY < gq.APPS < gq.INDEX < gq.VISION
    assert gq.NAMES[gq.APPS] == "apps" and len(gq.NAMES) == 5


def test_an_app_waits_for_a_family_chat():
    with gq.use(gq.CHAT):
        waited = gq.wait_turn(gq.APPS, max_wait=0.2)
    assert waited >= 0.15


def test_one_request_per_key():
    first = ai_apps.Slot("tok1")
    with pytest.raises(ai_apps.KeyBusy):
        ai_apps.Slot("tok1")
    other = ai_apps.Slot("tok2")  # another app isn't held up
    first.release()
    first.release()  # twice is harmless
    with ai_apps.Slot("tok1"):
        pass
    other.release()
    assert not ai_apps._BUSY


def test_chat_and_embeddings_run_as_apps(monkeypatch):
    kinds = []
    real_use = gq.use

    def use(kind):
        kinds.append(kind)
        return real_use(kind)

    monkeypatch.setattr(gq, "use", use)
    monkeypatch.setattr(gq, "wait_turn", lambda kind, max_wait=30: kinds.append(("wait", kind)) or 0.0)

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"choices": []}'

    monkeypatch.setattr(ai_apps, "_first_answering", lambda body, timeout: (Resp(), "m"))
    monkeypatch.setattr("backend.services.chat_llm_runtime.mark_chat_activity", lambda: None)
    ai_apps.chat({"messages": []})
    monkeypatch.setattr(ai_apps, "_config", lambda: {"embedding_model": "eg2"})
    monkeypatch.setattr("backend.services.rag_embeddings.embedding_host", lambda cfg: "h")
    monkeypatch.setattr(
        "backend.services.rag_embeddings.compute_neural_embedding_via_ollama", lambda text, **k: (b"", [0.1])
    )
    ai_apps.embeddings({"input": ["a"]})
    assert kinds == [("wait", gq.APPS), gq.APPS, ("wait", gq.APPS), gq.APPS]


def _key(client, auth_headers):
    r = client.post("/api/v1/ai/apps/keys", headers=auth_headers, json={"app": "other", "name": "x"})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    return {"Authorization": f"Bearer {body.get('key') or body.get('token')}"}


def test_the_api_answers_429_while_the_key_is_busy(client, auth_headers, monkeypatch):
    monkeypatch.setattr("backend.services.ai_access.allowed", lambda p: True)
    monkeypatch.setattr("backend.services.ai_access.log_request", lambda *a, **k: None)
    headers = _key(client, auth_headers)
    gate, started = threading.Event(), threading.Event()

    def slow(body):
        started.set()
        gate.wait(5)
        return {"object": "list", "data": []}

    monkeypatch.setattr(ai_apps, "embeddings", slow)
    out = {}
    t = threading.Thread(
        target=lambda: out.setdefault(
            "r", client.post("/api/v1/ai/openai/embeddings", headers=headers, json={"input": "a"})
        )
    )
    t.start()
    assert started.wait(5)
    busy = client.post("/api/v1/ai/openai/embeddings", headers=headers, json={"input": "b"})
    gate.set()
    t.join(5)
    assert busy.status_code == 429 and busy.json()["error"]["type"] == "rate_limit_error"
    assert out["r"].status_code == 200
    assert client.post("/api/v1/ai/openai/embeddings", headers=headers, json={"input": "c"}).status_code == 200
