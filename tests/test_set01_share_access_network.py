"""SET-01: over the network, shared folders follow the people as they are now.

- An administrator opens every shared folder (a new one used to be off for everyone on a new
  install), whatever the folder's own list says.
- The Samba settings are rewritten when a person is added or removed, after the Security Advisor's
  fix for kids and guests, and at start.
"""

import pytest

from backend import main
from backend.services import safe_defaults_advisor, samba_engine, share_access
from backend.services.samba_engine import SambaShareConfig, access_lines
from backend.users_db import create_user, delete_user, get_user_by_username


@pytest.fixture
def refreshed(monkeypatch):
    calls = []
    monkeypatch.setattr(samba_engine, "refresh_access", lambda: calls.append(1))
    return calls


def _lines(share="media"):
    return access_lines(SambaShareConfig(name=share, path=f"/mnt/user/{share}"))


def _person(name, role):
    return get_user_by_username(name) or create_user(name, name.title(), "GoodPass123!", role_id=role)


def _valid(lines):
    return lines[0].split("=", 1)[1].split()


def test_an_administrator_is_always_in_a_folders_list():
    kid, store = _person("net_kid", "kid"), _person("net_store", "storage_admin")
    try:
        share_access.save_config({"default_level": "none", "shares": {}})
        valid = _valid(_lines())
        assert "admin" in valid and "net_store" in valid and "net_kid" not in valid
        # the folder's own list cannot take an administrator out, or make one read-only
        share_access.save_config(
            {"default_level": "none", "shares": {"media": {"users": {"admin": "none", "net_store": "read"}}}}
        )
        lines = _lines()
        assert {"admin", "net_store"} <= set(_valid(lines))
        assert not any(line.strip().startswith("read list") for line in lines)
    finally:
        delete_user(kid["id"])
        delete_user(store["id"])


def test_the_roles_that_manage_every_folder():
    roles = samba_engine._files_admin_roles()
    assert "superadmin" in roles and "storage_admin" in roles
    assert not roles & {"kid", "guest", "share_user"}


def test_adding_and_removing_a_person_rewrites_the_network_lists(refreshed):
    person = create_user("net_new", "New", "GoodPass123!", role_id="kid")
    assert len(refreshed) == 1
    assert delete_user(person["id"]) is True
    assert len(refreshed) == 2


def test_the_advisors_fix_reaches_the_network(refreshed):
    share_access.save_config({"default_level": "write", "shares": {}})
    safe_defaults_advisor._fix_share_access_family()
    assert share_access.load_config()["role_defaults"] == {"kid": "none", "guest": "none"}
    assert refreshed == [1]


def test_the_lists_are_rewritten_at_start(refreshed):
    main._refresh_share_access()
    assert refreshed == [1]
