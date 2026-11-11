"""SET-05: an upload never replaces a file without being told to.

Both upload paths ended in os.replace(): a file of the same name was overwritten, with no
question and no copy in the Recycle Bin. A caller that says nothing now gets "name (2)". "ask"
answers 409 before any byte is stored, so the page can ask the person (the owner's decision S16).
"replace" puts the old file in the Recycle Bin first."""

import os
import shutil

import pytest

from backend.api.files import uploads
from backend.config import POOL_PATH as POOL_DIR

FOLDER = os.path.join(POOL_DIR, "set05_uploads")


@pytest.fixture
def folder():
    root_bin = os.path.join(POOL_DIR, ".RecycleBin")
    had_root_bin = os.path.exists(root_bin)
    shutil.rmtree(FOLDER, ignore_errors=True)
    os.makedirs(FOLDER)
    with open(os.path.join(FOLDER, "report.txt"), "w") as f:
        f.write("the first one")
    yield FOLDER
    shutil.rmtree(FOLDER, ignore_errors=True)
    if not had_root_bin:  # the pool is shared with every other test: leave it as it was
        shutil.rmtree(root_bin, ignore_errors=True)


def _read(*parts):
    with open(os.path.join(FOLDER, *parts)) as f:
        return f.read()


def _upload(client, headers, name, data, **params):
    return client.post(
        "/api/fs/upload", params={"path": FOLDER, "filename": name, **params}, content=data, headers=headers
    )


def _chunked(client, headers, name, data, **extra):
    init = client.post(
        "/api/fs/upload/init",
        json={"destination_dir": FOLDER, "filename": name, "total_size": len(data), **extra},
        headers=headers,
    )
    if init.status_code != 200:
        return init
    uid = init.json()["upload_id"]
    r = client.post(f"/api/fs/upload/chunk?upload_id={uid}&chunk_index=0", content=data, headers=headers)
    assert r.status_code == 200, r.text
    return client.post("/api/fs/upload/complete", json={"upload_id": uid}, headers=headers)


@pytest.mark.parametrize("send", [_upload, _chunked])
def test_saying_nothing_keeps_both(client, auth_headers, folder, send):
    r = send(client, auth_headers, "report.txt", b"the second one")
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "report (2).txt" and r.json()["renamed"] is True
    assert _read("report.txt") == "the first one" and _read("report (2).txt") == "the second one"
    r = send(client, auth_headers, "report.txt", b"the third one")
    assert r.json()["name"] == "report (3).txt"
    assert sorted(os.listdir(folder)) == ["report (2).txt", "report (3).txt", "report.txt"]


@pytest.mark.parametrize("send, key", [(_upload, {"on_conflict": "ask"}), (_chunked, {"on_conflict": "ask"})])
def test_ask_answers_before_anything_is_stored(client, auth_headers, folder, send, key):
    r = send(client, auth_headers, "report.txt", b"the second one", **key)
    assert r.status_code == 409 and r.json()["error"] == "name_taken"
    assert "report.txt" in r.json()["detail"]
    assert os.listdir(folder) == ["report.txt"] and _read("report.txt") == "the first one"  # no staging left either
    # a name that is free goes through with "ask"
    r = send(client, auth_headers, "other.txt", b"new", **key)
    assert r.status_code == 200 and r.json()["name"] == "other.txt" and r.json()["renamed"] is False


@pytest.mark.parametrize("send", [_upload, _chunked])
def test_replace_puts_the_old_file_in_the_recycle_bin(client, auth_headers, folder, send):
    r = send(client, auth_headers, "report.txt", b"the second one", on_conflict="replace")
    assert r.status_code == 200 and r.json()["name"] == "report.txt" and r.json()["renamed"] is False
    assert _read("report.txt") == "the second one"
    binned = client.get("/api/fs/trash", headers=auth_headers).json()["items"]
    mine = [i for i in binned if str(i.get("original_path", "")).endswith("set05_uploads/report.txt")]
    assert len(mine) == 1
    restored = client.post(
        "/api/fs/trash/restore", json={"item_id": mine[0]["id"], "target_path": folder}, headers=auth_headers
    )
    assert restored.status_code == 200
    with open(restored.json()["path"]) as f:
        assert f.read() == "the first one"


def test_a_file_never_replaces_a_folder(client, auth_headers, folder):
    os.makedirs(os.path.join(folder, "Photos"))
    r = _upload(client, auth_headers, "Photos", b"x", on_conflict="replace")
    assert r.status_code == 409 and r.json()["error"] == "name_taken" and "folder" in r.json()["detail"]
    assert os.path.isdir(os.path.join(folder, "Photos"))
    r = _upload(client, auth_headers, "Photos", b"x")
    assert r.status_code == 200 and r.json()["name"] == "Photos (2)"


def test_an_unknown_choice_is_refused(client, auth_headers, folder):
    assert _upload(client, auth_headers, "report.txt", b"x", on_conflict="overwrite").status_code == 400
    assert _chunked(client, auth_headers, "report.txt", b"x", on_conflict="overwrite").status_code == 400
    assert _read("report.txt") == "the first one"


def test_free_name():
    assert uploads._free_name(FOLDER + "-nothing-here", "a.tar.gz") == "a.tar.gz"
