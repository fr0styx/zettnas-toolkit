"""
tests/test_ai_conversations.py — Test suite for ZettAI multi-turn conversation persistence & REST API.
"""

import os

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.ai_conversations_db import (
    append_message,
    clear_all_conversations,
    create_conversation,
    delete_conversation,
    generate_auto_title_heuristic,
    get_conversation,
    get_conversation_with_messages,
    get_token_budgeted_history,
    init_conversations_db,
    list_conversations,
    update_auto_title_if_not_customized,
    update_conversation,
)


@pytest.fixture
def temp_conv_db(tmp_path, monkeypatch):
    """Sets up an isolated SQLite WAL conversation database for test duration."""
    db_file = str(tmp_path / "test_ai_conversations.db")
    monkeypatch.setenv("AI_CONVERSATIONS_DB_PATH", db_file)
    init_conversations_db(db_file)
    return db_file


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_auth_headers():
    return {"Authorization": "Bearer test-admin-token", "X-Forwarded-User": "admin"}


@pytest.fixture
def user2_auth_headers():
    return {"Authorization": "Bearer test-user2-token", "X-Forwarded-User": "charlie"}


# ---------------------------------------------------------------------------
# Direct Service & DB Layer Unit Tests
# ---------------------------------------------------------------------------


def test_conversation_crud_and_pinning(temp_conv_db):
    """Verifies conversation thread creation, retrieval, updates, and pin-based ordering."""
    # 1. Create threads
    c1 = create_conversation(user_id="alice", title="Docker Crash Debugging", model="deepseek-r1:1.5b")
    c2 = create_conversation(user_id="alice", title="Fan Curve Calibration", model="qwen2.5:3b")
    assert c1["id"].startswith("conv_")
    assert c1["title"] == "Docker Crash Debugging"
    assert c1["user_id"] == "alice"
    assert c1["is_pinned"] is False

    # 2. List threads (c2 should be first due to later updated_at)
    threads = list_conversations(user_id="alice")
    assert len(threads) == 2
    assert threads[0]["id"] == c2["id"]

    # 3. Pin c1 -> c1 should now be first
    updated_c1 = update_conversation(conv_id=c1["id"], user_id="alice", is_pinned=True)
    assert updated_c1["is_pinned"] is True

    threads_after_pin = list_conversations(user_id="alice")
    assert threads_after_pin[0]["id"] == c1["id"]
    assert threads_after_pin[1]["id"] == c2["id"]


def test_message_append_and_full_stream(temp_conv_db):
    """Verifies appending multi-modal messages, telemetry, citations, and full stream retrieval."""
    c = create_conversation(user_id="bob", title="Storage Audit")
    cid = c["id"]

    # 1. Append user message
    m1 = append_message(
        conv_id=cid,
        user_id="bob",
        role="user",
        content="Which hard drives are currently sleeping in my array?",
    )
    assert m1["role"] == "user"
    assert m1["content"] == "Which hard drives are currently sleeping in my array?"

    # 2. Append assistant response with tools and citations
    m2 = append_message(
        conv_id=cid,
        user_id="bob",
        role="assistant",
        content="All 4 array hard drives are currently in STANDBY mode (0 RPM).",
        telemetry={"active_model": "deepseek-r1:1.5b", "tokens_per_sec": 42.5},
        tools_called=[{"tool": "get_disks_and_standby_status", "summary": "4 drives in standby"}],
        citations=[{"source": "/mnt/user/system.log", "confidence": 0.98}],
    )
    assert m2["role"] == "assistant"
    assert m2["telemetry"]["tokens_per_sec"] == 42.5
    assert len(m2["tools_called"]) == 1

    # 3. Fetch conversation with messages
    full = get_conversation_with_messages(cid, user_id="bob")
    assert full is not None
    assert full["message_count"] == 2
    assert full["messages"][0]["id"] == m1["id"]
    assert full["messages"][1]["id"] == m2["id"]
    assert full["messages"][1]["citations"][0]["confidence"] == 0.98


def test_multi_user_isolation(temp_conv_db):
    """Verifies that threads and messages belonging to User A cannot be accessed or deleted by User B."""
    c_alice = create_conversation(user_id="alice", title="Alice Secrets")
    append_message(c_alice["id"], "alice", "user", "Private prompt for Alice")

    # Bob tries to access Alice's conversation
    assert get_conversation(c_alice["id"], user_id="bob") is None
    assert get_conversation_with_messages(c_alice["id"], user_id="bob") is None
    assert list_conversations(user_id="bob") == []

    # Bob tries to update or delete Alice's conversation
    assert update_conversation(c_alice["id"], user_id="bob", title="Hacked") is None
    assert delete_conversation(c_alice["id"], user_id="bob") is False

    # Verify Alice's conversation remains intact
    alice_conv = get_conversation_with_messages(c_alice["id"], user_id="alice")
    assert alice_conv is not None
    assert alice_conv["title"] == "Alice Secrets"


def test_fts5_full_text_search(temp_conv_db):
    """Verifies instant FTS5 matching on keywords in messages and conversation titles."""
    c1 = create_conversation(user_id="dave", title="Network Setup")
    append_message(c1["id"], "dave", "user", "Configure WireGuard mesh tunnel on port 51820")

    c2 = create_conversation(user_id="dave", title="Postgres Database Backup")
    append_message(c2["id"], "dave", "user", "Create hyper-backup snapshot for database container")

    # Search for "WireGuard" -> matches c1
    res_wg = list_conversations(user_id="dave", search="WireGuard")
    assert len(res_wg) == 1
    assert res_wg[0]["id"] == c1["id"]

    # Search for "Postgres" -> matches c2
    res_pg = list_conversations(user_id="dave", search="Postgres")
    assert len(res_pg) == 1
    assert res_pg[0]["id"] == c2["id"]

    # Search for "backup" -> matches c2
    res_bk = list_conversations(user_id="dave", search="backup")
    assert len(res_bk) == 1
    assert res_bk[0]["id"] == c2["id"]


def test_auto_title_heuristic_and_customization_guard(temp_conv_db):
    """Verifies automatic title generation and Title Customization Guard (title_customized = 1)."""
    # 1. Test heuristic cleaner
    t1 = generate_auto_title_heuristic("Can you please tell me which hard drives are sleeping in my array?")
    assert "Hard drives are sleeping in" in t1 or "Hard Drives" in t1

    t2 = generate_auto_title_heuristic("How do I configure fan curve for quiet profile?")
    assert "Configure Fan Curve" in t2 or "Fan Curve" in t2

    # 2. Test auto-titler updates thread when title_customized == 0
    c = create_conversation(user_id="eve", title="New Conversation")
    cid = c["id"]
    new_t = update_auto_title_if_not_customized(cid, "eve", "How do I configure fan curve for quiet profile?")
    assert new_t != "New Conversation"

    c_fetched = get_conversation(cid, "eve")
    assert c_fetched["title"] == new_t
    assert c_fetched["title_customized"] is False

    # 3. User explicitly renames the thread -> title_customized becomes 1
    update_conversation(cid, "eve", title="My Custom Fan Curve")
    c_renamed = get_conversation(cid, "eve")
    assert c_renamed["title"] == "My Custom Fan Curve"
    assert c_renamed["title_customized"] is True

    # 4. Subsequent turns MUST NOT overwrite customized title
    t_after = update_auto_title_if_not_customized(cid, "eve", "What is the CPU temp right now?")
    assert t_after == "My Custom Fan Curve"
    assert get_conversation(cid, "eve")["title"] == "My Custom Fan Curve"


def test_token_budgeted_sliding_window_compaction(temp_conv_db):
    """Verifies that conversation history budgeter compacts older turns and strips bulky data."""
    c = create_conversation(user_id="frank", title="Long Conversation")
    cid = c["id"]

    # Append 6 turns
    for i in range(1, 7):
        append_message(cid, "frank", "user", f"Turn {i} question about NAS subsystem {i}")
        append_message(cid, "frank", "assistant", f"Turn {i} detailed answer explaining subsystem {i}")

    # Extract history with strict 300 token budget (~1200 chars)
    history = get_token_budgeted_history(cid, "frank", max_tokens=150)
    assert len(history) >= 2  # At least Turn N-1 user + assistant must be retained
    # Latest turn must be present
    assert "Turn 6" in history[-1]["content"]


def test_cascading_delete_and_clear_all(temp_conv_db):
    """Verifies cascading deletion of messages when a thread is deleted or when all are cleared."""
    c1 = create_conversation(user_id="grace", title="Thread 1")
    append_message(c1["id"], "grace", "user", "Hello 1")
    c2 = create_conversation(user_id="grace", title="Thread 2")
    append_message(c2["id"], "grace", "user", "Hello 2")

    assert len(list_conversations(user_id="grace")) == 2

    # Delete single thread
    ok = delete_conversation(c1["id"], user_id="grace")
    assert ok is True
    assert get_conversation(c1["id"], user_id="grace") is None
    assert len(list_conversations(user_id="grace")) == 1

    # Clear all remaining
    deleted_cnt = clear_all_conversations(user_id="grace")
    assert deleted_cnt == 1
    assert len(list_conversations(user_id="grace")) == 0


# ---------------------------------------------------------------------------
# REST API Endpoint Integration Tests
# ---------------------------------------------------------------------------


def test_api_conversations_rest_lifecycle(client, auth_headers, temp_conv_db):
    """Tests the full REST lifecycle: POST, GET, PATCH, DELETE /api/ai/conversations."""
    # 1. Create thread via POST
    res_create = client.post(
        "/api/ai/conversations",
        json={"title": "REST API Test Thread", "model": "qwen2.5:3b"},
        headers=auth_headers,
    )
    assert res_create.status_code == 200
    data_c = res_create.json()
    assert data_c["status"] == "ok"
    conv_id = data_c["conversation"]["id"]
    assert data_c["conversation"]["title"] == "REST API Test Thread"

    # 2. List threads via GET
    res_list = client.get("/api/ai/conversations", headers=auth_headers)
    assert res_list.status_code == 200
    convs = res_list.json()["conversations"]
    assert any(c["id"] == conv_id for c in convs)

    # 3. Append message via POST /api/ai/conversations/{conv_id}/messages
    res_msg = client.post(
        f"/api/ai/conversations/{conv_id}/messages",
        json={"role": "user", "content": "How fast is my NVMe pool?"},
        headers=auth_headers,
    )
    assert res_msg.status_code == 200
    assert res_msg.json()["status"] == "ok"

    # 4. Get full thread via GET /api/ai/conversations/{conv_id}
    res_get = client.get(f"/api/ai/conversations/{conv_id}", headers=auth_headers)
    assert res_get.status_code == 200
    c_full = res_get.json()["conversation"]
    assert c_full["id"] == conv_id
    assert len(c_full["messages"]) == 1
    assert c_full["messages"][0]["content"] == "How fast is my NVMe pool?"

    # 5. Patch thread via PATCH /api/ai/conversations/{conv_id}
    res_patch = client.patch(
        f"/api/ai/conversations/{conv_id}",
        json={"title": "NVMe Speed Benchmarks", "is_pinned": True},
        headers=auth_headers,
    )
    assert res_patch.status_code == 200
    c_patched = res_patch.json()["conversation"]
    assert c_patched["title"] == "NVMe Speed Benchmarks"
    assert c_patched["is_pinned"] is True

    # 6. Delete thread via DELETE /api/ai/conversations/{conv_id}
    res_del = client.delete(f"/api/ai/conversations/{conv_id}", headers=auth_headers)
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # Verify 404 after deletion
    res_404 = client.get(f"/api/ai/conversations/{conv_id}", headers=auth_headers)
    assert res_404.status_code == 404


def test_api_chat_with_conversation_id_persists_turns(client, auth_headers, temp_conv_db):
    """Verifies that passing conversation_id to /api/ai/chat automatically persists turns and auto-titles."""
    from unittest.mock import patch

    # 1. Create a fresh thread
    res_c = client.post(
        "/api/ai/conversations",
        json={"title": "New Conversation", "model": "test-model"},
        headers=auth_headers,
    )
    assert res_c.status_code == 200
    cid = res_c.json()["conversation"]["id"]

    # 2. Call /api/ai/chat with conversation_id
    mock_run_res = {
        "status": "ok",
        "reply": "All 4 hard drives are in standby.",
        "active_model": "test-model",
        "llm_telemetry": {"active_model": "test-model"},
        "tools_called": [{"tool": "get_disks_and_standby_status", "summary": "4 drives in standby"}],
    }
    with patch("backend.api.media.run_agentic_chat", return_value=mock_run_res):
        res_chat = client.post(
            "/api/ai/chat",
            json={
                "message": "Which hard drives are sleeping in my array?",
                "conversation_id": cid,
            },
            headers=auth_headers,
        )
        assert res_chat.status_code == 200
        data = res_chat.json()
        assert data["conversation_id"] == cid
        assert "Hard Drives" in data.get("conversation_title", "") or "Hard drives" in data.get(
            "conversation_title", ""
        )

    # 3. Retrieve conversation with messages from DB
    res_get = client.get(f"/api/ai/conversations/{cid}", headers=auth_headers)
    assert res_get.status_code == 200
    c_data = res_get.json()["conversation"]
    assert len(c_data["messages"]) == 2
    assert c_data["messages"][0]["role"] == "user"
    assert "Which hard drives are sleeping" in c_data["messages"][0]["content"]
    assert c_data["messages"][1]["role"] == "assistant"
    assert "All 4 hard drives are in standby." in c_data["messages"][1]["content"]
    assert len(c_data["messages"][1]["tools_called"]) == 1


# ---------------------------------------------------------------------------
# ZettAI Tools & Fast Math Reasoning Tests
# ---------------------------------------------------------------------------


def test_tool_calculate_arithmetic_and_expressions():
    """Verifies that tool_calculate evaluates arithmetic, functions, percentages, and conversions safely."""
    from backend.services.ai_chat_agent import (
        _is_math_or_calculation_query,
        tool_calculate,
    )

    # 1. Natural language query detection
    assert _is_math_or_calculation_query("Whats 67+20?") is True
    assert _is_math_or_calculation_query("Calculate 125 * 8") is True
    assert _is_math_or_calculation_query("What is 15% of 80?") is True
    assert _is_math_or_calculation_query("List my docker containers") is False
    assert _is_math_or_calculation_query("Why is CPU fan spinning at 1500 RPM?") is False

    # 2. Basic arithmetic
    res1 = tool_calculate("Whats 67+20?")
    assert res1["status"] == "ok"
    assert res1["result"] == 87

    # 3. Percentages
    res2 = tool_calculate("15% of 80")
    assert res2["status"] == "ok"
    assert res2["result"] == 12.0

    # 4. Safe math functions
    res3 = tool_calculate("sqrt(144) + 10")
    assert res3["status"] == "ok"
    assert res3["result"] == 22.0

    # 5. Storage unit conversions
    res4 = tool_calculate("16 TB to TiB")
    assert res4["status"] == "ok"
    assert "TiB" in str(res4.get("formatted", ""))


def test_tool_get_storage_and_network_status():
    """Verifies get_storage_status and get_network_status execute without waking sleeping HDDs."""
    from backend.services.ai_chat_agent import (
        tool_get_network_status,
        tool_get_storage_status,
    )

    storage_res = tool_get_storage_status()
    assert storage_res["status"] == "ok"
    assert "pools" in storage_res
    assert storage_res.get("zero_disk_wakeups") is True

    net_res = tool_get_network_status()
    assert net_res["status"] == "ok"
    assert "interfaces" in net_res
    assert "default_gateway" in net_res


def test_resolve_model_runtime_accelerator(monkeypatch):
    """The device comes from the model's server, never from its name (AI-29)."""
    from backend.services import ai_device
    from backend.services.ai_chat_agent import resolve_model_runtime_accelerator

    host_accel = {"has_npu": True, "has_igpu": True, "active_tier": 1, "device_label": "Intel AI Boost NPU"}
    reported = {}
    monkeypatch.setattr(ai_device, "device_for", lambda ep, model: reported.get(model))

    # A name that says "NPU" proves nothing: not reported means not reported
    res = resolve_model_runtime_accelerator("DeepSeek-R1-Distill-Qwen-1.5B", host_accel, endpoint="http://ovms:8000/v3")
    assert res["active_tier"] == 0 and res["device_label"] == "Not reported by OpenVINO Model Server"

    reported["DeepSeek-R1-Distill-Qwen-1.5B"] = "NPU"
    res = resolve_model_runtime_accelerator("DeepSeek-R1-Distill-Qwen-1.5B", host_accel, endpoint="http://ovms:8000/v3")
    assert res["tier_code"] == "NPU_TIER_1" and res["name"] == "Intel AI Boost NPU"

    reported["qwen2.5:3b"] = "GPU"
    res = resolve_model_runtime_accelerator("qwen2.5:3b", host_accel, endpoint="http://ollama:11434")
    assert res["tier_code"] == "GPU_TIER_2" and res["runtime_engine"] == "Ollama (GPU)"


def test_math_query_bypasses_web_and_disk_tools():
    """Verifies that asking a math question like 'Whats 67+20?' invokes calculate, bypasses web search, and does not check disks."""
    from backend.services.ai_chat_agent import run_agentic_chat

    res = run_agentic_chat(
        "Whats 67+20?",
        history=[
            {"role": "user", "content": "How long will my hard drives last in standby?"},
            {"role": "assistant", "content": "Hard drives typically last 3-5 years."},
        ],
        allow_web_search=True,
        allow_nas_tools=True,
    )

    assert res["status"] == "ok"
    tool_names = res.get("tool_names", [])

    # calculate must have run
    assert "calculate" in tool_names

    # Neither web search nor disk checks should have run
    assert "browse_internet" not in tool_names
    assert "get_disks_and_standby_status" not in tool_names

    # Telemetry should reflect 0 disk wakeups and active calculation
    assert "87" in str(res.get("reply", ""))


def test_weather_tool_and_country_disambiguation_santo_domingo():
    """Verifies that asking about weather in Santo Domingo calls get_weather, flags ambiguity, and prompts for country confirmation."""
    # Test direct tool invocation with deterministic test weather
    from backend.services.ai_chat_agent import _WEB_ALLOWED, run_agentic_chat, tool_get_weather

    token = _WEB_ALLOWED.set(True)  # the weather tool only runs with web access on
    try:
        data = tool_get_weather("Santo Domingo")
    finally:
        _WEB_ALLOWED.reset(token)
    assert data["location"] == "Santo Domingo"
    assert data["is_ambiguous"] is True
    assert len(data["candidates"]) == 2
    assert any("Dominican Republic" in opt["country"] for opt in data["candidates"])
    assert any("Chile" in opt["country"] for opt in data["candidates"])

    # Test agentic chat execution
    res = run_agentic_chat(
        "Whats the weather in Santo Domingo?",
        history=[],
        allow_web_search=True,
        allow_nas_tools=True,
    )
    assert res["status"] == "ok"
    assert "get_weather" in res.get("tool_names", [])
    reply = res.get("reply", "")
    assert len(reply.strip()) > 0
    assert "Santo Domingo" in reply
    assert "Dominican Republic" in reply
    assert "Chile" in reply


def test_weather_country_confirmation_followup():
    """Verifies that replying to a weather disambiguation prompt with a country name confirms the target location."""
    from backend.services.ai_chat_agent import run_agentic_chat

    history = [
        {"role": "user", "content": "Whats the weather in Santo Domingo?"},
        {
            "role": "assistant",
            "content": "Which country do you mean for Santo Domingo? 1: Dominican Republic, 2: Chile",
        },
    ]
    res = run_agentic_chat(
        "Dominican Republic please",
        history=history,
        allow_web_search=True,
        allow_nas_tools=True,
    )
    assert res["status"] == "ok"
    assert "get_weather" in res.get("tool_names", [])
    reply = res.get("reply", "")
    assert "Dominican Republic" in reply


def test_empty_think_recovery_synthesizes_grounded_answer():
    """Verifies that if an LLM spends all tokens inside <think>...</think> and leaves outside text blank, a grounded reply is generated."""
    from unittest.mock import patch

    from backend.services.ai_chat_agent import run_agentic_chat

    mock_llm_return = (
        "<think>Examining meteorological data for Santo Domingo. Temperatures are warm with trade winds.</think>",
        "Mock-LLM-Runtime",
        50,
        28.0,
        {"tier_code": "GPU_TIER_2", "name": "Intel Arc GPU"},
        None,
    )

    with patch("backend.services.ai_chat_agent._try_local_llm_completion", return_value=mock_llm_return):
        res = run_agentic_chat(
            "Whats the weather in Santo Domingo?",
            history=[],
            allow_web_search=True,
            allow_nas_tools=True,
        )
        assert res["status"] == "ok"
        reply = res.get("reply", "")
        # The reply must not be empty or blank
        assert len(reply.strip()) > 0
        # The synthesized response should contain the weather details
        assert "Santo Domingo" in reply


def test_unclosed_think_recovery_synthesizes_grounded_answer():
    """Verifies that if an LLM is truncated mid-generation with an unclosed <think> tag, a grounded reply is generated."""
    from unittest.mock import patch

    from backend.services.ai_chat_agent import extract_and_strip_reasoning, run_agentic_chat

    mock_llm_return = (
        "<think>Examining meteorological data for Santo Domingo. Temperatures are warm with trade winds...",
        "Mock-LLM-Runtime",
        50,
        28.0,
        {"tier_code": "GPU_TIER_2", "name": "Intel Arc GPU"},
        None,
    )

    with patch("backend.services.ai_chat_agent._try_local_llm_completion", return_value=mock_llm_return):
        res = run_agentic_chat(
            "Whats the weather in Santo Domingo?",
            history=[],
            allow_web_search=True,
            allow_nas_tools=True,
        )
        assert res["status"] == "ok"
        reply = res.get("reply", "")
        assert len(reply.strip()) > 0
        assert "Santo Domingo" in reply
        extracted_think, clean_reply = extract_and_strip_reasoning(reply)
        assert (
            extracted_think
            == "Examining meteorological data for Santo Domingo. Temperatures are warm with trade winds..."
        )
        assert "Santo Domingo" in clean_reply
        assert "<think>" not in clean_reply
