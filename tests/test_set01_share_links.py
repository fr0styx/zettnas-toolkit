"""SET-01: share links can be seen and stopped by whoever made them, and hand out no more than
the folder shows.

- Family members and kids could make a link but were refused the list and the stop.
- A link that never ends could be made with no password.
- A folder link also carried the folder's Recycle Bin and uploads that were not finished.
- Links that ended stayed in the file for ever.
"""

import io
import json
import os
import shutil
import time
import zipfile
from unittest.mock import patch

import pytest

import backend.api.fs as fs_mod
from backend.api.files import share_links
from backend.fsutil import left_out_of_downloads
from backend.users_db import create_user, get_user_by_username


@pytest.fixture
def sandbox(tmp_path, pool_tree):
    links_file = str(tmp_path / "shared_links.json")
    fs_mod._SHARE_PWD_ATTEMPTS.clear()
    with (
        patch.object(share_links, "SHARE_LINKS_FILE", links_file),
        patch.object(fs_mod, "ALLOWED_BROWSE_ROOTS", [str(pool_tree)]),
    ):
        yield {"links_file": links_file, "pool": pool_tree, "file": os.path.join(pool_tree, "media", "readme.txt")}
    fs_mod._SHARE_PWD_ATTEMPTS.clear()


def _family(client):
    if not get_user_by_username("link_fam"):
        create_user("link_fam", "Fam", "GoodPass123!", role_id="share_user")
    res = client.post("/api/auth/login", json={"username": "link_fam", "password": "GoodPass123!"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _link(sandbox, token, **fields):
    try:
        with open(sandbox["links_file"], encoding="utf-8") as fh:
            links = json.load(fh)
    except FileNotFoundError:
        links = {}
    links[token] = {
        "token": token,
        "path": sandbox["file"],
        "filename": "readme.txt",
        "created_at": time.time(),
        **fields,
    }
    with open(sandbox["links_file"], "w", encoding="utf-8") as fh:
        json.dump(links, fh)


def test_a_link_that_never_ends_needs_a_password(client, auth_headers, sandbox):
    body = {"path": sandbox["file"], "expires_hours": None}
    refused = client.post("/api/fs/share-links", json=body, headers=auth_headers)
    assert refused.status_code == 400 and "needs a password" in refused.text
    upload = client.post(
        "/api/fs/share-links",
        json={"path": os.path.dirname(sandbox["file"]), "expires_hours": 0, "kind": "upload"},
        headers=auth_headers,
    )
    assert upload.status_code == 400
    ok = client.post("/api/fs/share-links", json={**body, "password": "Open-Sesame-1"}, headers=auth_headers)
    assert ok.status_code == 200 and ok.json()["has_password"] is True and ok.json()["expires_at"] is None
    day = client.post("/api/fs/share-links", json={"path": sandbox["file"]}, headers=auth_headers)
    assert day.status_code == 200  # nothing said: one day
    assert 86000 < day.json()["expires_at"] - time.time() <= 86400


def test_whoever_may_make_a_link_sees_and_stops_their_own(client, auth_headers, sandbox):
    family = _family(client)
    _link(sandbox, "mine", created_by="link_fam")
    _link(sandbox, "theirs", created_by="admin")
    listed = client.get("/api/fs/share-links", headers=family)
    assert listed.status_code == 200
    assert [item["token"] for item in listed.json()] == ["mine"]  # their own only
    assert client.delete("/api/fs/share-links/theirs", headers=family).status_code == 403
    assert client.delete("/api/fs/share-links/mine", headers=family).status_code == 200
    assert client.get("/api/fs/share-links", headers=family).json() == []
    everyone = client.get("/api/fs/share-links", headers=auth_headers).json()
    assert [item["token"] for item in everyone] == ["theirs"]  # an administrator sees all


def test_a_folder_link_leaves_out_the_bin_and_unfinished_uploads(client, auth_headers, sandbox):
    folder = os.path.join(sandbox["pool"], "handout")
    os.makedirs(os.path.join(folder, ".RecycleBin"), exist_ok=True)
    os.makedirs(os.path.join(folder, ".kiboto_staging_abc_film.mkv"), exist_ok=True)
    for name in ("keep.txt", ".RecycleBin/deleted.txt", ".kiboto_tmp_abc_film.mkv", ".kiboto_staging_abc_film.mkv/0"):
        with open(os.path.join(folder, name), "w") as fh:
            fh.write("x")
    try:
        made = client.post("/api/fs/share-links", json={"path": folder, "expires_hours": 24}, headers=auth_headers)
        assert made.status_code == 200, made.text
        got = client.get(f"/api/fs/shared/{made.json()['token']}")
        assert got.status_code == 200, got.text
        names = zipfile.ZipFile(io.BytesIO(got.content)).namelist()
        assert [os.path.basename(n) for n in names] == ["keep.txt"], names
        assert share_links._folder_size_capped(folder, 10) == 1
    finally:
        shutil.rmtree(folder)  # the pool is shared with other tests: leave no Recycle Bin behind


def test_names_a_download_never_carries():
    assert left_out_of_downloads(".RecycleBin") and left_out_of_downloads(".kiboto_tmp_1_a.bin")
    assert left_out_of_downloads(".kiboto_staging_1_a.bin")
    assert not left_out_of_downloads("RecycleBin") and not left_out_of_downloads(".hidden-note")


def test_links_that_ended_long_ago_leave_the_file(client, auth_headers, sandbox):
    now = time.time()
    _link(sandbox, "old", created_by="admin", expires_at=now - 8 * 86400)
    _link(sandbox, "recent", created_by="admin", expires_at=now - 3600)
    _link(sandbox, "open", created_by="admin", expires_at=None)
    made = client.post("/api/fs/share-links", json={"path": sandbox["file"], "expires_hours": 1}, headers=auth_headers)
    assert made.status_code == 200
    with open(sandbox["links_file"], encoding="utf-8") as fh:
        kept = set(json.load(fh))
    assert kept == {"recent", "open", made.json()["token"]}
    listed = {item["token"]: item for item in client.get("/api/fs/share-links", headers=auth_headers).json()}
    assert listed["recent"]["is_expired"] is True  # still shown as ended for a week
    assert client.delete("/api/fs/share-links/open", headers=auth_headers).status_code == 200
