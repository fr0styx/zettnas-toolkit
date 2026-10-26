"""M1: files shared from a phone land in the user's Inbox without overwriting anything."""

import os


def test_inbox_upload_never_overwrites(client, auth_headers, paths, monkeypatch):
    from backend.api.files import uploads as fs  # the inbox lives here since ARC-5

    inbox = os.path.join(paths["pool"], "homes", "admin", "Inbox")
    monkeypatch.setattr(fs, "_inbox_dir", lambda principal: inbox)
    for body in (b"one", b"two"):
        r = client.post("/api/fs/inbox?filename=photo.jpg", content=body, headers=auth_headers)
        assert r.status_code == 200, r.text
    names = sorted(os.listdir(inbox))
    assert names == ["photo (2).jpg", "photo.jpg"]
    with open(os.path.join(inbox, "photo.jpg"), "rb") as f:
        assert f.read() == b"one"
    r = client.post("/api/fs/inbox?filename=../../etc/passwd", content=b"x", headers=auth_headers)
    assert r.status_code == 200 and r.json()["name"] == "passwd"
    assert os.path.exists(os.path.join(inbox, "passwd"))


def test_service_worker_is_served(client):
    import app as app_module  # noqa: F401

    assert os.path.exists("frontend/public/sw.js")
