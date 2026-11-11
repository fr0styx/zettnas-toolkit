"""SET-13: read marks are saved with the account, and clearing the event log leaves a record."""

from backend import state
from backend.users_db import create_user, get_user_by_username


def test_seen_up_to_is_saved_with_the_account(client):
    if not get_user_by_username("log_lena"):
        create_user("log_lena", "Lena", "GoodPass123!", role_id="share_user")
    token = client.post("/api/auth/login", json={"username": "log_lena", "password": "GoodPass123!"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert "events_seen" not in client.get("/api/auth/me", headers=headers).json()["preferences"]
    res = client.put("/api/auth/me/preferences", json={"events_seen": 1791394800}, headers=headers)
    assert res.status_code == 200 and res.json()["preferences"]["events_seen"] == 1791394800
    # another device of the same person reads it back; their other settings are untouched
    client.put("/api/auth/me/preferences", json={"clock_format": "24"}, headers=headers)
    prefs = client.get("/api/auth/me", headers=headers).json()["preferences"]
    assert prefs["events_seen"] == 1791394800 and prefs["clock_format"] == "24"
    assert client.put("/api/auth/me/preferences", json={"events_seen": -5}, headers=headers).status_code == 422


def test_clearing_the_log_says_who_did_it(client, auth_headers):
    state.add_event("info", "Before", "an older entry")
    assert client.delete("/api/events/clear", headers=auth_headers).status_code == 200
    (entry,) = state.events_snapshot()
    assert entry["kind"] == "log_cleared" and entry["level"] == "warning"
    assert entry["details"]["params"]["who"] and entry["details"]["params"]["who"] in entry["message"]
