"""The terminal WebSocket resolves credentials only through the session store (audit pass 2)."""

import asyncio
from types import SimpleNamespace


def test_unresolved_token_is_not_the_admin(monkeypatch):
    import backend.api.docker as docker_api
    import backend.auth as auth_mod
    import backend.users_db as users_db

    monkeypatch.setattr(auth_mod, "get_current_session", lambda t: None)
    monkeypatch.setattr(users_db, "validate_user_session", lambda t: None)
    monkeypatch.setattr(users_db, "validate_scoped_api_token", lambda t: None)
    monkeypatch.setattr(auth_mod, "validate_session", lambda t: True)
    ws = SimpleNamespace(
        query_params={},
        cookies={"zettnas_session": "dummy"},
        headers={"origin": "http://h", "host": "h"},
        client=SimpleNamespace(host="203.0.113.5"),
    )
    assert asyncio.run(docker_api._authenticate_ws(ws)) is False
