"""Security event alerts and rate limits (Batch 2)."""

import time

from backend import rate_limit
from backend.services import security_alerts


def test_important_events_are_sent_and_others_are_not(monkeypatch):
    sent = []
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda *a, **k: sent.append((a, k)))
    assert security_alerts.maybe_alert("api_token.created", "success", "boss", "10.0.0.5", {"name": "ci"})
    assert not security_alerts.maybe_alert("auth.login.success", "success", "boss")
    for _ in range(50):
        if sent:
            break
        time.sleep(0.02)
    (title, message), kwargs = sent[0]
    assert "API token created" in title and "boss" in message and "10.0.0.5" in message
    assert kwargs["event_type"] == "security" and kwargs["dedup_key"].startswith("sec:api_token.created")


def test_lockout_and_role_change_reach_the_audit_log(client, auth_headers, monkeypatch):
    events = []
    monkeypatch.setattr("backend.services.security_alerts.maybe_alert", lambda e, *a, **k: events.append(e) or True)
    from backend.api import auth as auth_api

    for _ in range(auth_api._FREE_ATTEMPTS_USER + 1):
        client.post("/api/auth/login", json={"username": "nobody-here", "password": "x"})
    assert "auth.lockout" in events
    for k in list(auth_api._failures):
        auth_api._clear_failures(k)

    from backend.users_db import create_user, get_user_by_username

    create_user("roleuser", "R", "GoodPass123!", role_id="share_user")
    uid = get_user_by_username("roleuser")["id"]
    res = client.put(f"/api/users/{uid}", json={"role_id": "auditor"}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert "user.role.changed" in events


def test_limiter_window():
    rate_limit.reset()
    assert all(rate_limit.hit("t:k", 3, 60) == 0 for _ in range(3))
    assert rate_limit.hit("t:k", 3, 60) > 0
    assert rate_limit.hit("t:other", 3, 60) == 0


def test_chat_is_rate_limited_per_user(client, auth_headers, monkeypatch):
    from backend.api import media

    monkeypatch.setattr(media, "run_agentic_chat", lambda *a, **k: {"status": "ok", "reply": "hi", "tools_called": []})
    codes = [client.post("/api/ai/chat", json={"message": "hi"}, headers=auth_headers).status_code for _ in range(22)]
    assert codes[:20] == [200] * 20 and codes[-1] == 429
