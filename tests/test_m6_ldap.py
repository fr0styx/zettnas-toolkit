"""LDAP / Active Directory sign-in against an in-memory ldap3 MOCK directory."""

import pytest
from ldap3 import MOCK_SYNC, OFFLINE_AD_2012_R2, Connection, Server

from backend.services import ldap_auth

BASE = "dc=home,dc=lan"


@pytest.fixture
def directory(tmp_path, monkeypatch):
    monkeypatch.setattr(ldap_auth, "CONFIG_FILE", str(tmp_path / "ldap.json"))
    server = Server("mock", get_info=OFFLINE_AD_2012_R2)
    seed = Connection(server, user="cn=svc,ou=svc," + BASE, password="svc-pass", client_strategy=MOCK_SYNC)
    seed.strategy.add_entry("cn=svc,ou=svc," + BASE, {"userPassword": "svc-pass", "sAMAccountName": "svc"})
    seed.strategy.add_entry(
        "cn=Alice Admin,ou=people," + BASE,
        {
            "userPassword": "alice-pw",
            "sAMAccountName": "dir.alice",
            "displayName": "Alice Admin",
            "mail": "alice@home.lan",
            "memberOf": ["cn=NAS Admins,ou=groups," + BASE],
            "objectClass": "person",
        },
    )
    seed.strategy.add_entry(
        "cn=Kid,ou=people," + BASE,
        {
            "userPassword": "kid-pw",
            "sAMAccountName": "dir.kid",
            "memberOf": ["cn=Family,ou=groups," + BASE],
            "objectClass": "person",
        },
    )
    seed.strategy.add_entry(
        "cn=Admin Clash,ou=people," + BASE, {"userPassword": "x-pw", "sAMAccountName": "admin", "objectClass": "person"}
    )

    def factory(cfg):
        return server

    # every connection shares the seeded mock directory
    monkeypatch.setattr(ldap_auth, "_SERVER_FACTORY", factory)
    orig = ldap_auth._connection

    def conn(srv, user, password, cfg):
        c = orig(srv, user, password, cfg)
        c.strategy.entries = seed.strategy.entries
        return c

    monkeypatch.setattr(ldap_auth, "_connection", conn)
    ldap_auth.save_config(
        {
            "enabled": True,
            "server_url": "ldaps://dc.home.lan",
            "base_dn": BASE,
            "bind_dn": "cn=svc,ou=svc," + BASE,
            "bind_password": "svc-pass",
            "admin_groups": ["NAS Admins"],
            "role_map": {"Family": "share_user"},
        }
    )
    return seed


def test_admin_group_member_signs_in_as_superadmin(directory):
    user = ldap_auth.login("dir.alice", "alice-pw")
    assert user["username"] == "dir.alice" and user["role_id"] == "superadmin" and user["idp_type"] == "ldap"
    assert ldap_auth.login("dir.alice", "wrong") is None
    assert ldap_auth.login("dir.alice", "") is None  # never an anonymous bind


def test_family_member_and_filter_injection(directory):
    assert ldap_auth.login("dir.kid", "kid-pw")["role_id"] == "share_user"
    assert ldap_auth.login("*", "kid-pw") is None
    assert ldap_auth.login("kid)(|(sAMAccountName=*", "kid-pw") is None


def test_never_takes_over_a_local_account(directory):
    from backend.users_db import get_user_by_username

    assert get_user_by_username("admin") is None or get_user_by_username("admin")["idp_type"] != "ldap"
    if get_user_by_username("admin") is not None:
        assert ldap_auth.login("admin", "x-pw") is None


def test_login_endpoint_uses_the_directory(client, directory):
    r = client.post("/api/auth/login", json={"username": "dir.kid", "password": "kid-pw"})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "dir.kid"
    assert client.post("/api/auth/login", json={"username": "dir.kid", "password": "nope"}).status_code == 401


def test_settings_api_masks_the_password(client, auth_headers, directory):
    s = client.get("/api/auth/ldap/settings", headers=auth_headers).json()
    assert s["bind_password"] == "********" and s["enabled"] is True
    bad = client.put("/api/auth/ldap/settings", json={"server_url": "http://x"}, headers=auth_headers)
    assert bad.status_code == 400
