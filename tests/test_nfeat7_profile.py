"""NFEAT-7: the family calendar and contacts as an iPhone profile."""

import plistlib

from backend.services import family_dav


def test_profile_holds_both_accounts_and_no_credentials():
    data = plistlib.loads(family_dav.ios_profile("nas.local", 8093))
    assert data["PayloadType"] == "Configuration"
    kinds = {p["PayloadType"]: p for p in data["PayloadContent"]}
    cal, card = kinds["com.apple.caldav.account"], kinds["com.apple.carddav.account"]
    assert cal["CalDAVHostName"] == "nas.local" and cal["CalDAVPort"] == 8093
    assert cal["CalDAVPrincipalURL"] == "/remote.php/dav" and cal["CalDAVUseSSL"] is False
    assert card["CardDAVHostName"] == "nas.local" and card["CardDAVPort"] == 8093
    text = plistlib.dumps(data).decode()
    assert "Username" not in text and "Password" not in text
    # the same profile each time, so installing it again replaces it
    assert family_dav.ios_profile("nas.local", 8093) == family_dav.ios_profile("nas.local", 8093)
    assert plistlib.loads(family_dav.ios_profile("h", None))["PayloadContent"][0]["CalDAVPort"] == 80


def test_profile_for_this_server(monkeypatch):
    monkeypatch.setattr(family_dav, "office_container", lambda: None)
    assert family_dav.ios_profile_for("nas.local") is None
    monkeypatch.setattr(family_dav, "office_container", lambda: {"name": "o", "running": True, "port": 8093})
    data = plistlib.loads(family_dav.ios_profile_for("nas.local"))
    assert data["PayloadContent"][0]["CalDAVHostName"] == "nas.local"


def test_profile_endpoint(client, auth_headers, monkeypatch):
    url = "/api/docker/catalog/office-suite/family/profile"
    monkeypatch.setattr(family_dav, "office_container", lambda: None)
    assert client.get(url, headers=auth_headers).status_code == 404
    monkeypatch.setattr(family_dav, "office_container", lambda: {"name": "o", "running": True, "port": 8093})
    res = client.get(url, headers=auth_headers)
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/x-apple-aspen-config")
    assert "mobileconfig" in res.headers["content-disposition"]
    assert plistlib.loads(res.content)["PayloadContent"][1]["CardDAVPort"] == 8093
