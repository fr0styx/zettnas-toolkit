"""SEC-36: remembered sessions keep their long idle limit, a password change can revoke your
own API tokens, and the 10,000 most common passwords are refused."""

import time

from backend import config, users_db
from backend.password_policy import password_problem


def test_common_and_short_passwords_are_refused():
    assert password_problem("qwerty123") and "most used" in password_problem("qwerty123")
    assert password_problem("ILoveYou")  # case doesn't help
    assert password_problem("short") and str(config.MIN_PASSWORD_LENGTH) in password_problem("short")
    assert password_problem("admin")
    assert password_problem("correct-horse-battery-staple-7") is None


def test_a_remembered_session_keeps_its_idle_limit_before_a_restart(tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    users_db.init_users_db(db)
    user = users_db.create_user("kim", "Kim", "a-Long-unique-pw-91", role_id="share_user", db_path=db)
    token = users_db.create_user_session(user["id"], "kim", is_remembered=True, db_path=db)
    cached = users_db._SESSION_CACHE[__import__("hashlib").sha256(token.encode()).hexdigest()]
    assert cached["is_remembered"] is True
    # four days without use: past the normal idle limit, within the remembered one
    later = time.time() + 4 * 86400
    assert config.SESSION_IDLE_SECS < 4 * 86400 < config.REMEMBERED_SESSION_IDLE_SECS
    monkeypatch.setattr(users_db.time, "time", lambda: later)
    assert users_db.validate_user_session(token, db_path=db)


def test_changing_your_own_password_can_revoke_your_tokens(client, auth_headers):
    me = client.get("/api/auth/me", headers=auth_headers).json()
    uid = (me.get("user") or me)["id"]
    tok = client.post("/api/tokens", json={"name": "script", "scopes": ["system:read"]}, headers=auth_headers)
    assert tok.status_code in (200, 201), tok.text
    assert users_db.list_user_api_tokens(uid)

    weak = client.post(
        f"/api/users/{uid}/password",
        json={"new_password": "password1", "current_password": "admin"},
        headers=auth_headers,
    )
    assert weak.status_code == 400 and weak.json().get("error") == "weak_password"
    r = client.post(
        f"/api/users/{uid}/password",
        json={"new_password": "a-New-unique-pw-73", "current_password": "admin", "revoke_tokens": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert users_db.list_user_api_tokens(uid) == []
