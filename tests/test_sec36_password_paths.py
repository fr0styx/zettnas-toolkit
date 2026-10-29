"""SEC-36: every place that sets a password refuses a weak one before doing anything else."""

from backend import config, password_policy


def test_the_default_password_is_refused_even_when_short_ones_are_allowed(monkeypatch):
    monkeypatch.setattr(config, "MIN_PASSWORD_LENGTH", 4)
    assert "default" in password_policy.password_problem("Admin")


def test_without_the_list_only_length_and_the_default_count(monkeypatch):
    monkeypatch.setattr(password_policy, "COMMON_FILE", "/nonexistent/common-passwords.txt")
    password_policy._common.cache_clear()
    try:
        assert password_policy._common() == frozenset()
        assert password_policy.password_problem("qwerty123") is None
    finally:
        monkeypatch.undo()
        password_policy._common.cache_clear()
    assert password_policy.password_problem("qwerty123")


def test_accepting_an_invite_refuses_a_common_password(client):
    r = client.post("/api/invite/not-a-real-token/accept", json={"username": "sam", "password": "qwerty123"})
    assert r.status_code == 400 and "most used" in r.json()["detail"]


def test_a_new_sftp_user_refuses_a_common_password(client, auth_headers, monkeypatch):
    from backend.api import sftp

    called = []
    monkeypatch.setattr(
        sftp, "get_sftp_engine", lambda: type("E", (), {"add_user": lambda self, d: called.append(d)})()
    )
    r = client.post(
        "/api/sftp/users",
        json={"username": "camera", "password": "qwerty123", "shares": []},
        headers=auth_headers,
    )
    assert r.status_code == 400 and "most used" in r.json()["detail"]
    assert called == []
