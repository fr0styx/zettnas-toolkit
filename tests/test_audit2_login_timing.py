"""Unknown usernames get a password check too (audit pass 2)."""

from backend.api import auth as auth_api


def test_unknown_username_still_runs_a_password_check(client, monkeypatch):
    seen = []
    real = auth_api.verify_password
    monkeypatch.setattr(auth_api, "verify_password", lambda pw, h: seen.append(h) or real(pw, h))
    r = client.post("/api/auth/login", json={"username": "no-such-user-x", "password": "wrong-pass-1"})
    assert r.status_code == 401
    assert seen and seen[0] == auth_api._dummy_hash()
