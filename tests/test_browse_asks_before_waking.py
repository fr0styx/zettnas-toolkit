"""Opening a folder on a sleeping disk asks first: listing it would spin the disk up."""

import pytest

from backend.api.files import browse as br


@pytest.fixture
def folder(tmp_path, monkeypatch):
    from backend import config

    d = tmp_path / "share"
    (d / "a.txt").parent.mkdir(parents=True)
    (d / "a.txt").write_text("x")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(tmp_path)])
    monkeypatch.setattr(br, "ALLOWED_BROWSE_ROOTS", [str(tmp_path)])
    monkeypatch.setattr("backend.api.files.common.ALLOWED_BROWSE_ROOTS", [str(tmp_path)], raising=False)
    return d


def _asleep(monkeypatch, value, dev="sdb"):
    monkeypatch.setattr("backend.services.rag_standby.resolve_path_backing_dev", lambda p: dev)
    monkeypatch.setattr("backend.services.rag_standby.is_backing_disk_in_standby", lambda d: value)


@pytest.mark.real_confirmations
def test_a_sleeping_disk_needs_a_yes(client, auth_headers, folder, monkeypatch):
    _asleep(monkeypatch, True)
    r = client.get("/api/browse", params={"path": str(folder)}, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "folder.wake"
    tok = client.post("/api/confirmations", headers=auth_headers, json={"action": "folder.wake", "target": str(folder)})
    assert tok.status_code == 200, tok.text
    ok = client.get(
        "/api/browse", params={"path": str(folder)}, headers={**auth_headers, "X-Confirm-Token": tok.json()["token"]}
    )
    assert ok.status_code == 200 and any(e["name"] == "a.txt" for e in ok.json()["dirs"])


def test_an_awake_or_unknown_disk_opens_at_once(client, auth_headers, folder, monkeypatch):
    _asleep(monkeypatch, False)
    assert client.get("/api/browse", params={"path": str(folder)}, headers=auth_headers).status_code == 200
    from backend.services.rag_standby import UNKNOWN_BACKING_DEV

    _asleep(monkeypatch, True, dev=UNKNOWN_BACKING_DEV)  # a remote or a USB stick: not held up
    assert client.get("/api/browse", params={"path": str(folder)}, headers=auth_headers).status_code == 200


def test_the_bin_view_and_bad_paths_are_not_held_up(monkeypatch):
    _asleep(monkeypatch, True)
    assert br.folder_asleep("/mnt/user/.RecycleBin") is False
    assert br.folder_asleep("/etc") is False  # refused later by the access check, not here
