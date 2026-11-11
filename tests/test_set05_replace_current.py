"""SET-05: "Replace current" in Previous versions keeps the file as it was in the Recycle Bin.

It overwrote the file with an earlier version, with no copy anywhere."""

import os
import shutil

import pytest

from backend.config import POOL_PATH as POOL_DIR
from backend.services import file_versions

FOLDER = os.path.join(POOL_DIR, "set05_versions")


@pytest.fixture
def doc(tmp_path, monkeypatch):
    shutil.rmtree(FOLDER, ignore_errors=True)
    os.makedirs(FOLDER)
    path = os.path.join(FOLDER, "plan.txt")
    with open(path, "w") as f:
        f.write("as it is today")
    old = tmp_path / "plan.txt"
    old.write_text("as it was last week")
    monkeypatch.setattr(file_versions, "version_path", lambda p, version_id: str(old))
    yield path
    shutil.rmtree(FOLDER, ignore_errors=True)


def test_replace_current_bins_the_file_as_it_was(client, auth_headers, doc):
    r = client.post(
        "/api/fs/versions/restore", json={"path": doc, "version": "v1", "overwrite": True}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["overwrote"] is True and r.json()["old_in_bin"] is True
    with open(doc) as f:
        assert f.read() == "as it was last week"
    binned = client.get("/api/fs/trash", headers=auth_headers).json()["items"]
    mine = [i for i in binned if str(i["original_path"]).endswith("set05_versions/plan.txt")]
    assert len(mine) == 1
    with open(mine[0]["path"]) as f:
        assert f.read() == "as it is today"


def test_a_copy_beside_the_file_bins_nothing(client, auth_headers, doc):
    r = client.post(
        "/api/fs/versions/restore", json={"path": doc, "version": "v1", "overwrite": False}, headers=auth_headers
    )
    assert r.status_code == 200 and r.json()["old_in_bin"] is False
    with open(doc) as f:
        assert f.read() == "as it is today"
    with open(r.json()["path"]) as f:
        assert f.read() == "as it was last week"
