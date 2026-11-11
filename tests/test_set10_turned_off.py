"""SET-10: a person who is turned off loses their network folders at once. Turning off ended only
the web session."""

import pytest

from backend import users_db
from backend.services import samba_engine

PW = "a-long-enough-pass-1"


@pytest.fixture
def switched(monkeypatch):
    calls = []

    class Engine:
        def set_account_enabled(self, username, enabled):
            calls.append((username, enabled))
            return True

        def sync_samba_user(self, **kw):
            return True

    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: Engine())
    monkeypatch.setattr(samba_engine, "refresh_access", lambda: calls.append("refresh"))
    return calls


def test_turning_a_person_off_and_on_switches_their_network_account(client, auth_headers, switched):
    user = users_db.create_user("set10off", "Otto", PW, role_id="share_user")
    try:
        switched.clear()
        r = client.put(f"/api/users/{user['id']}", json={"status": "disabled"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert switched == [("set10off", False), "refresh"]
        switched.clear()
        assert (
            client.put(f"/api/users/{user['id']}", json={"status": "active"}, headers=auth_headers).status_code == 200
        )
        assert switched == [("set10off", True), "refresh"]
        switched.clear()
        client.put(f"/api/users/{user['id']}", json={"display_name": "Otto K."}, headers=auth_headers)
        assert not [c for c in switched if isinstance(c, tuple)]  # a name change switches nothing
    finally:
        users_db.delete_user(user["id"])


def test_the_switch_keeps_the_password_and_refuses_odd_names(monkeypatch):
    ran = []

    class Done:
        returncode = 0

    monkeypatch.setattr(samba_engine.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or Done())
    engine = samba_engine.SambaEngine()
    assert engine.set_account_enabled("otto", False) and engine.set_account_enabled("otto", True)
    assert ran == [["smbpasswd", "-d", "otto"], ["smbpasswd", "-e", "otto"]]  # off and on: never removed
    assert engine.set_account_enabled("otto; rm -rf /", False) is False and len(ran) == 2


def test_services_above_follow_through_a_hook(monkeypatch):
    seen = []
    monkeypatch.setattr(users_db, "_STATUS_HOOKS", [])
    monkeypatch.setattr(users_db, "test_mode", lambda: False)
    monkeypatch.setattr(users_db, "get_user_by_id", lambda uid, **kw: {"id": uid, "username": "otto"})
    monkeypatch.setattr(
        samba_engine, "get_samba_engine", lambda: type("E", (), {"set_account_enabled": lambda self, n, a: True})()
    )
    users_db.on_status_change(lambda user, active: seen.append((user["username"], active)))
    users_db.on_status_change(lambda user, active: (_ for _ in ()).throw(RuntimeError("down")))  # one that fails
    started = []
    monkeypatch.setattr(
        users_db.threading,
        "Thread",
        lambda target, **kw: started.append(target) or type("T", (), {"start": lambda self: target()})(),
    )
    users_db._network_follows_status("usr_x", False)
    assert seen == [("otto", False)] and len(started) == 1


def test_the_start_registers_family_sign_in(monkeypatch):
    from backend import main
    from backend.services import family_signin

    synced = []
    monkeypatch.setattr(family_signin, "config", lambda: {"enabled": True})
    monkeypatch.setattr(family_signin, "sync", lambda actor="": synced.append(actor))
    main._family_signin_follows_status({"username": "otto"}, False)
    monkeypatch.setattr(family_signin, "config", lambda: {})
    main._family_signin_follows_status({"username": "otto"}, True)
    assert synced == ["status change"]
