"""Folder listings in the File Explorer (backend/api/fs.py): entries and their details,
the parent entry, links that leave the storage folders, private folders under homes/,
and unreadable folders."""

import os

import pytest
from fastapi import HTTPException

from backend.api import fs as fs_api
from backend.auth import AuthenticatedPrincipal
from backend.config import POOL_PATH


def _who(name, role="share_user", scopes=("shares:read",)):
    return AuthenticatedPrincipal(username=name, role_id=role, scopes=list(scopes), is_admin=False)


@pytest.fixture
def tree(pool_tree, tmp_path):
    root = os.path.join(POOL_PATH, "browse-test")
    os.makedirs(os.path.join(root, "Docs"), exist_ok=True)
    with open(os.path.join(root, "notes.TXT"), "w") as f:
        f.write("12345")
    os.chmod(os.path.join(root, "notes.TXT"), 0o640)
    inside = os.path.join(root, "to-docs")
    if not os.path.lexists(inside):
        os.symlink(os.path.join(root, "Docs"), inside)
    outside = os.path.join(root, "to-etc")
    if not os.path.lexists(outside):
        os.symlink(str(tmp_path), outside)
    return root


def _names(res):
    return [e["name"] for e in res["dirs"]]


def test_listing_details(tree):
    res = fs_api._handle_browse_logic_unfiltered(tree, False, None)
    assert res["current"] == os.path.realpath(tree)
    by = {e["name"]: e for e in res["dirs"]}
    assert _names(res)[0] == ".." and by[".."]["path"] == os.path.dirname(os.path.realpath(tree))
    assert by["notes.TXT"]["size"] == 5 and by["notes.TXT"]["ext"] == ".txt" and by["notes.TXT"]["mode"] == "0640"
    assert by["Docs"]["is_dir"] is True and by["Docs"]["size"] == 0 and by["Docs"]["ext"] == ""
    assert by["to-docs"]["is_symlink"] is True
    # a link that leaves the storage folders is not listed at all
    assert "to-etc" not in by


def test_folders_only(tree):
    res = fs_api._handle_browse_logic_unfiltered(tree, True, None)
    assert "notes.TXT" not in _names(res) and "Docs" in _names(res)


def test_the_storage_root_has_no_parent_entry(pool_tree):
    res = fs_api._handle_browse_logic_unfiltered(POOL_PATH, False, None)
    assert ".." not in _names(res)


@pytest.mark.parametrize(("path", "code"), [("", None), ("/etc", 403), ("\x00", 400)])
def test_bad_paths(pool_tree, path, code):
    if code is None:  # empty means the first storage folder
        assert fs_api._handle_browse_logic_unfiltered(path, False, None)["current"]
        return
    with pytest.raises(HTTPException) as e:
        fs_api._handle_browse_logic_unfiltered(path, False, None)
    assert e.value.status_code == code


def test_a_file_is_not_a_folder(tree):
    with pytest.raises(HTTPException) as e:
        fs_api._handle_browse_logic_unfiltered(os.path.join(tree, "notes.TXT"), False, None)
    assert e.value.status_code == 400


def test_homes_shows_people_only_their_own_folder(pool_tree):
    homes = os.path.join(POOL_PATH, "homes")
    for name in ("alice", "bob"):
        os.makedirs(os.path.join(homes, name), exist_ok=True)
    res = fs_api._handle_browse_logic_unfiltered(homes, False, _who("alice"))
    assert [n for n in _names(res) if n != ".."] == ["alice"]
    # administrators see everyone
    admin = _who("root", role="superadmin", scopes=("*",))
    assert {"alice", "bob"} <= set(_names(fs_api._handle_browse_logic_unfiltered(homes, False, admin)))
    # a person without a folder yet gets one, listed at once (it used to show only after a reload)
    res = fs_api._handle_browse_logic_unfiltered(homes, False, _who("Carol"))
    assert "carol" in _names(res) and os.path.isdir(os.path.join(homes, "carol"))


def test_listdir_fallback_and_unreadable_folders(tree, monkeypatch):
    def no_scandir(path):
        raise OSError("scandir unsupported here")

    monkeypatch.setattr(fs_api.os, "scandir", no_scandir)
    res = fs_api._handle_browse_logic_unfiltered(tree, False, None)
    by = {e["name"]: e for e in res["dirs"]}
    assert by["notes.TXT"]["size"] == 5 and by["Docs"]["is_dir"] and "to-etc" not in by

    def denied(path):
        raise PermissionError("no")

    monkeypatch.setattr(fs_api.os, "listdir", denied)
    with pytest.raises(HTTPException) as e:
        fs_api._handle_browse_logic_unfiltered(tree, False, None)
    assert e.value.status_code == 403

    def broken(path):
        raise OSError("I/O error")

    monkeypatch.setattr(fs_api.os, "listdir", broken)
    with pytest.raises(HTTPException) as e:
        fs_api._handle_browse_logic_unfiltered(tree, False, None)
    assert e.value.status_code == 500


def test_browse_route(client, auth_headers, tree):
    r = client.get("/api/browse", params={"path": tree}, headers=auth_headers)
    assert r.status_code == 200 and "notes.TXT" in [e["name"] for e in r.json()["dirs"]]
