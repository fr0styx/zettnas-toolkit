"""SEC-10: non-admin users reach only their home and the shares granted to them."""

import pytest
from fastapi import HTTPException

from backend import config
from backend.api.fs import _handle_browse_logic, check_user_path_access
from backend.auth import AuthenticatedPrincipal
from backend.services import share_access


def _user(name):
    return AuthenticatedPrincipal(
        {
            "user_id": f"u_{name}",
            "username": name,
            "role_id": "share_user",
            "scopes": ["shares:read", "shares:user_write"],
        }
    )


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "user"
    for d in ("media", "private", "homes/alice", "homes/bob", "appdata/app", "rawdisk"):
        (root / d).mkdir(parents=True)
    (root / "media" / "song.mp3").write_text("x")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)])
    monkeypatch.setattr(
        share_access,
        "known_shares",
        lambda: [
            {"name": "media", "path": str(root / "media"), "samba": None},
            {
                "name": "private",
                "path": str(root / "private"),
                "samba": {"valid": {"bob"}, "read": set(), "write": set(), "read_only": False},
            },
        ],
    )
    share_access.invalidate()
    return root


def test_a_new_install_gives_no_share_until_it_is_granted(tree):
    alice = _user("alice")
    check_user_path_access(str(tree / "homes" / "alice"), alice, write=True)
    with pytest.raises(HTTPException) as e:
        check_user_path_access(str(tree / "media" / "song.mp3"), alice)
    assert e.value.status_code == 403
    share_access.save_config({"shares": {"media": {"users": {"alice": "write"}}}})
    check_user_path_access(str(tree / "media" / "song.mp3"), alice, write=True)


def test_an_upgraded_install_keeps_write_access_to_shares_but_not_other_folders(tree):
    share_access.save_config({"default_level": "write", "shares": {}})
    alice = _user("alice")
    check_user_path_access(str(tree / "media" / "song.mp3"), alice, write=True)
    check_user_path_access(str(tree / "homes" / "alice"), alice, write=True)
    for path in (tree / "rawdisk", tree / "private", tree / "homes" / "bob"):
        with pytest.raises(HTTPException) as e:
            check_user_path_access(str(path), alice)
        assert e.value.status_code == 403
    # the folder above the shares can be listed (browse only) but not read or written
    check_user_path_access(str(tree), alice, allow_list=True)
    with pytest.raises(HTTPException):
        check_user_path_access(str(tree), alice)
    with pytest.raises(HTTPException):
        check_user_path_access(str(tree), alice, write=True)


def test_levels_from_config_and_samba_lists(tree):
    share_access.save_config(
        {"default_level": "none", "shares": {"media": {"default": "read", "users": {"bob": "write"}}}}
    )
    alice, bob = _user("alice"), _user("bob")
    check_user_path_access(str(tree / "media"), alice)
    with pytest.raises(HTTPException) as e:
        check_user_path_access(str(tree / "media" / "new.txt"), alice, write=True)
    assert "read-only" in e.value.detail
    check_user_path_access(str(tree / "media" / "new.txt"), bob, write=True)
    check_user_path_access(str(tree / "private"), bob, write=True)  # Samba valid users


def test_symlink_out_of_a_share_is_judged_by_its_target(tree):
    (tree / "media" / "escape").symlink_to(tree / "rawdisk")
    with pytest.raises(HTTPException):
        check_user_path_access(str(tree / "media" / "escape"), _user("alice"))


def test_browse_hides_folders_the_user_cannot_reach(tree):
    share_access.save_config({"shares": {"media": {"users": {"alice": "read"}}}})
    listing = _handle_browse_logic(str(tree), False, _user("alice"))
    names = {e["name"] for e in listing["dirs"]}
    assert {"media", "homes"} <= names
    assert not names & {"private", "rawdisk", "appdata"}


def test_admin_api_round_trip(client, auth_headers, tree):
    res = client.put(
        "/api/storage/share-access",
        json={"default_level": "read", "shares": {"media": {"users": {"Alice": "none"}}}},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    got = client.get("/api/storage/share-access", headers=auth_headers).json()
    assert got["default_level"] == "read"
    assert {s["name"] for s in got["shares"]} == {"media", "private"}
    bad = client.put("/api/storage/share-access", json={"default_level": "root"}, headers=auth_headers)
    assert bad.status_code == 400
