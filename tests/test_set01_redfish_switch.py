"""SET-01: Redfish is off until an administrator turns it on, and needs a right when on.

It used to answer on every install: its first page to anyone, without sign-in, and every other page
to any signed-in account. The SNMP routes are gone: they answered "engine active" for an agent that
never existed.
"""

import pytest

from backend.services import redfish_access
from backend.users_db import create_user, get_user_by_username

PAGES = ("/redfish/v1/", "/redfish/v1", "/redfish/v1/Chassis", "/redfish/v1/Systems/1", "/redfish/v1/Storage/1")


@pytest.fixture
def switch(tmp_path, monkeypatch):
    monkeypatch.setattr(redfish_access, "SETTINGS_FILE", str(tmp_path / "redfish.json"))
    return redfish_access


def _login(client, name, role):
    if not get_user_by_username(name):
        create_user(name, name, "GoodPass123!", role_id=role)
    res = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_off_by_default_and_every_page_says_so(client, auth_headers, switch):
    assert switch.enabled() is False
    for page in PAGES:
        assert client.get(page, headers=auth_headers).status_code == 404, page


def test_no_page_answers_without_sign_in(client, switch):
    switch.set_enabled(True)
    for page in PAGES:
        assert client.get(page).status_code == 401, page


def test_when_on_it_needs_a_right_to_read_the_system(client, auth_headers, switch):
    switch.set_enabled(True)
    kid = _login(client, "rf_kid", "kid")
    for page in PAGES:
        assert client.get(page, headers=kid).status_code == 403, page
        assert client.get(page, headers=auth_headers).status_code == 200, page


def test_an_administrator_turns_it_on_and_off_and_it_is_logged(client, auth_headers, switch, monkeypatch):
    logged = []
    monkeypatch.setattr("backend.users_db.log_security_event", lambda *a, **k: logged.append(a[0]))
    assert client.get("/api/system/redfish", headers=auth_headers).json() == {"enabled": False}
    on = client.put("/api/system/redfish", json={"enabled": True}, headers=auth_headers)
    assert on.status_code == 200 and on.json() == {"enabled": True}
    assert client.get("/redfish/v1/", headers=auth_headers).status_code == 200
    off = client.put("/api/system/redfish", json={"enabled": False}, headers=auth_headers)
    assert off.json() == {"enabled": False}
    assert client.get("/redfish/v1/", headers=auth_headers).status_code == 404
    assert logged == ["redfish.enabled", "redfish.disabled"]
    family = _login(client, "rf_fam", "share_user")
    assert client.put("/api/system/redfish", json={"enabled": True}, headers=family).status_code == 403
    assert client.get("/api/system/redfish", headers=family).status_code == 403


def test_the_snmp_routes_are_gone(client, auth_headers):
    for path in ("/api/snmp/status", "/api/snmp/config", "/api/snmp/oids", "/api/snmp/mib"):
        assert client.get(path, headers=auth_headers).status_code == 404, path
