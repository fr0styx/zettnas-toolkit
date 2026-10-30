"""NSEC-7: an account's sign-in hours hold for its API tokens, WebDAV and SFTP too."""

import inspect

from backend import auth


def test_a_token_outside_its_hours_is_refused(monkeypatch):
    tok = {
        "user_id": "u1",
        "username": "mia",
        "role_id": "share_user",
        "scopes": ["files:read"],
        "signin_hours": {"days": [0], "start": "08:00", "end": "09:00"},
    }
    monkeypatch.setattr(auth, "validate_scoped_api_token", lambda t: dict(tok))
    monkeypatch.setattr("backend.users_db.note_token_use", lambda *a, **k: None)
    monkeypatch.setattr("backend.signin_hours.allowed", lambda hours: False)
    assert auth.get_current_session("zat_x") is None
    monkeypatch.setattr("backend.signin_hours.allowed", lambda hours: True)
    assert auth.get_current_session("zat_x")["username"] == "mia"
    tok.pop("signin_hours")
    monkeypatch.setattr("backend.signin_hours.allowed", lambda hours: False)
    assert auth.get_current_session("zat_x")["username"] == "mia"  # no hours set: no limit


def test_the_token_lookup_carries_the_hours():
    from backend import users_db

    src = inspect.getsource(users_db.validate_scoped_api_token)
    assert "u.signin_hours_json" in src and '"signin_hours": _signin_hours_of(row)' in src


def test_webdav_and_sftp_check_the_hours_without_counting_a_failure():
    from backend.services import rclone_auth_proxy

    src = inspect.getsource(rclone_auth_proxy.main)
    i = src.index("if not allowed(from_json(")
    assert "sys.exit(1)" in src[i : i + 400] and "register_failure" not in src[i : i + 400]
