"""SET-04: a chat typed without "+ New Chat" is saved.

Such a chat had no conversation: the list said "No conversations yet" beside the exchange, and
"Clear Chat" destroyed the only copy. The page now asks the server to start one."""

import pytest

from backend.api import media as media_api


@pytest.fixture
def kib(tmp_path, monkeypatch):
    from backend.services.ai_conversations_db import init_conversations_db

    db_file = str(tmp_path / "conversations.db")
    monkeypatch.setenv("AI_CONVERSATIONS_DB_PATH", db_file)
    init_conversations_db(db_file)
    monkeypatch.setattr(
        media_api,
        "run_agentic_chat",
        lambda message, *a, **k: {"status": "ok", "reply": f"an answer to: {message}", "tools_called": []},
    )


def _conversations(client, headers):
    return client.get("/api/ai/conversations", headers=headers).json()["conversations"]


def test_a_first_message_starts_a_conversation_and_is_kept(client, auth_headers, kib):
    before = {c["id"] for c in _conversations(client, auth_headers)}
    r = client.post(
        "/api/ai/chat", json={"message": "how do I prune roses", "new_conversation": True}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]
    try:
        assert conv_id and conv_id not in before
        assert conv_id in {c["id"] for c in _conversations(client, auth_headers)}
        saved = client.get(f"/api/ai/conversations/{conv_id}", headers=auth_headers).json()["conversation"]
        texts = [m["content"] for m in saved["messages"]]
        assert texts == ["how do I prune roses", "an answer to: how do I prune roses"]
        # the next message goes to the same conversation
        r = client.post(
            "/api/ai/chat",
            json={"message": "and when", "conversation_id": conv_id, "new_conversation": False},
            headers=auth_headers,
        )
        assert r.json()["conversation_id"] == conv_id
        saved = client.get(f"/api/ai/conversations/{conv_id}", headers=auth_headers).json()["conversation"]
        assert len(saved["messages"]) == 4
    finally:
        client.delete(f"/api/ai/conversations/{conv_id}", headers=auth_headers)


def test_a_caller_that_does_not_ask_gets_no_saved_chat(client, auth_headers, kib):
    before = {c["id"] for c in _conversations(client, auth_headers)}
    r = client.post("/api/ai/chat", json={"message": "what is 2 + 2"}, headers=auth_headers)
    assert r.status_code == 200 and "conversation_id" not in r.json()
    assert {c["id"] for c in _conversations(client, auth_headers)} == before


def test_an_existing_conversation_is_not_replaced(client, auth_headers, kib):
    conv_id = client.post("/api/ai/conversations", json={"title": "Roses"}, headers=auth_headers).json()[
        "conversation"
    ]["id"]
    try:
        before = {c["id"] for c in _conversations(client, auth_headers)}
        r = client.post(
            "/api/ai/chat",
            json={"message": "hello", "conversation_id": conv_id, "new_conversation": True},
            headers=auth_headers,
        )
        assert r.json()["conversation_id"] == conv_id
        assert {c["id"] for c in _conversations(client, auth_headers)} == before
    finally:
        client.delete(f"/api/ai/conversations/{conv_id}", headers=auth_headers)
