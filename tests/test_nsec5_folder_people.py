"""NSEC-5: an encrypted folder has its own list of people who may open it, its maker at first."""

from types import SimpleNamespace

import pytest

from backend.services import encrypted_folders as ef
from backend.services import encrypted_index as ei
from tests.test_feat13_encrypted_folders import FakeGocryptfs, box  # noqa: F401 (the fixture)

PW = "correct horse battery staple"


def who(name, manage=False):
    return SimpleNamespace(username=name, has_scope=lambda s: manage and s in ("shares:manage", "*"))


@pytest.fixture
def accounts(monkeypatch):
    users = [{"username": "Mum"}, {"username": "mia"}, {"username": "leo"}]
    monkeypatch.setattr("backend.users_db.list_users", lambda: users)
    return users


def test_a_new_folder_opens_only_for_its_maker(box, accounts):
    ef.create("Family", "Medical", PW, owner="Mum")
    assert ei.people_of("Medical") == ["Mum"]
    assert ef.listing()[0]["people"] == ["Mum"]
    assert ei.may_open("Medical", "mum") and not ei.may_open("Medical", "mia")
    ef.create("Family", "Old", PW)  # made before the list existed: the share decides
    assert ei.people_of("Old") is None and ei.may_open("Old", "anyone")


def test_choosing_people(box, accounts):
    ef.create("Family", "Medical", PW, owner="Mum")
    assert ef.set_people("Medical", ["mia", "MIA", "Mum"]) == {"name": "Medical", "people": ["mia", "Mum"]}
    with pytest.raises(ValueError, match="no account called"):
        ef.set_people("Medical", ["stranger"])
    with pytest.raises(ValueError, match="at least one"):
        ef.set_people("Medical", [])
    with pytest.raises(KeyError):
        ef.set_people("Nope", ["mia"])
    assert ef.set_people("Medical", None)["people"] is None


def test_the_readable_view_follows_the_list(box, accounts, monkeypatch):
    from backend.services import share_access

    ef.create("Family", "Medical", PW, owner="Mum")
    monkeypatch.setattr(
        share_access, "known_shares", lambda: [{"name": "Family", "path": str(box.family), "samba": {}}]
    )
    monkeypatch.setattr(share_access, "_user", lambda u: {"role_id": "share_user"})
    monkeypatch.setattr(share_access, "_home_for", lambda u, user: "")
    cfg = {
        "shares": {"Family": {"users": {"mum": "write", "mia": "read", "leo": "read"}}},
        "role_defaults": {},
        "default_level": "none",
    }
    monkeypatch.setattr(share_access, "load_config", lambda: cfg)
    assert (ef.plain_path("Medical"), "write") in share_access.grants_for("mum")
    assert (ef.plain_path("Medical"), "none") in share_access.grants_for("mia")  # she may read the share, not this
    ef.set_people("Medical", ["Mum", "mia"])
    assert (ef.plain_path("Medical"), "read") in share_access.grants_for("mia")
    assert (ef.plain_path("Medical"), "none") in share_access.grants_for("leo")


def test_opening_and_locking_follow_the_list(box, accounts, monkeypatch):
    from backend.api import encrypted_folders as api

    ef.create("Family", "Medical", PW, owner="Mum")
    monkeypatch.setattr("backend.services.app_catalog.share_mounts", lambda: {"Family": str(box.family)})
    monkeypatch.setattr("backend.services.share_access.level_for", lambda u, p: "write")
    assert api._can_use(who("Mum"), "Family", True, "Medical")
    assert not api._can_use(who("mia"), "Family", True, "Medical")  # writes the share, isn't on the list
    assert api._can_use(who("admin", manage=True), "Family", True, "Medical")


def test_the_api(client, auth_headers, box, accounts):
    r = client.post(
        "/api/encrypted-folders", headers=auth_headers, json={"share": "Family", "name": "Medical", "password": PW}
    )
    assert r.status_code == 200
    me = client.get("/api/encrypted-folders", headers=auth_headers).json()["folders"][0]["people"]
    assert me and len(me) == 1  # the account that made it
    ok = client.put("/api/encrypted-folders/Medical/people", headers=auth_headers, json={"people": ["mia"]})
    assert ok.status_code == 200 and ok.json()["people"] == ["mia"]
    bad = client.put("/api/encrypted-folders/Medical/people", headers=auth_headers, json={"people": ["stranger"]})
    assert bad.status_code == 400
    assert (
        client.put("/api/encrypted-folders/Nope/people", headers=auth_headers, json={"people": None}).status_code == 404
    )
