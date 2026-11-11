"""NFEAT-2: "send me files" links: people without an account drop files into one folder."""

import re

import pytest

from backend.api.files import upload_links
from backend.users_db import create_user, update_user_profile


@pytest.fixture
def setup(client, auth_headers, monkeypatch, tmp_path):
    from backend.api import fs as fs_api

    pool = tmp_path / "pool"
    inbox = pool / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "secret.txt").write_text("not for senders")
    for mod in (fs_api, fs_api.common, fs_api.share_links):
        monkeypatch.setattr(mod, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(fs_api.share_links, "SHARE_LINKS_FILE", str(tmp_path / "links.json"))
    monkeypatch.setattr("backend.config.POOL_PATH", str(pool))

    def make(**extra):
        r = client.post(
            "/api/fs/share-links", json={"path": str(inbox), "kind": "upload", **extra}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        return r.json()

    return {"pool": pool, "inbox": inbox, "make": make, "fs": fs_api}


def send(client, token, name, data, **headers):
    return client.post(f"/api/fs/shared/{token}/upload", content=data, headers={"X-File-Name": name, **headers})


def test_files_arrive_and_the_folder_is_never_shown(client, setup):
    link = setup["make"](label="Grandma's photos")
    assert link["kind"] == "upload" and link["max_upload_mb"] == upload_links.DEFAULT_LIMIT_MB
    page = client.get(f"/api/fs/shared/{link['token']}", headers={"Accept": "text/html"})
    assert page.status_code == 200 and "Send files to <strong>Grandma&#x27;s photos</strong>" in page.text
    assert "secret.txt" not in page.text and "script-src 'sha256-" in page.headers["content-security-policy"]
    info = client.get(f"/api/fs/shared/{link['token']}", params={"info": True}).json()
    assert info["kind"] == "upload" and "path" not in info and info["size_bytes"] == 0 and info["is_dir"]
    r = send(client, link["token"], "beach%20day.jpg", b"jpeg bytes")
    assert r.status_code == 200 and r.json() == {"name": "beach day.jpg", "size": 10}
    r = send(client, link["token"], "beach%20day.jpg", b"another")
    assert r.json()["name"] == "beach day (2).jpg"  # never overwritten
    assert (setup["inbox"] / "beach day.jpg").read_bytes() == b"jpeg bytes"
    assert not [p for p in setup["inbox"].iterdir() if p.name.startswith(".kb-upload")]
    listed = client.get("/api/fs/share-links", headers={"Authorization": client.headers.get("Authorization", "")})
    assert listed.status_code in (200, 401)


def test_names_cannot_leave_the_folder_or_hide(client, setup):
    token = setup["make"]()["token"]
    for raw, want in (
        ("..%2F..%2Fetc%2Fpasswd", "passwd"),
        (".bashrc", "_bashrc"),
        ("a%00b.txt", "ab.txt"),
        ("", "file"),
    ):
        assert send(client, token, raw, b"x").json()["name"] == want
    assert not (setup["pool"] / "passwd").exists()
    assert upload_links.safe_name(".kb-upload-x.part") == "_kb-upload-x.part"


def test_limits_size_and_length(client, setup):
    token = setup["make"](max_upload_mb=1)["token"]
    big = b"x" * (1024 * 1024 + 1)
    assert send(client, token, "big.bin", big).status_code == 413
    assert send(client, token, "ok.bin", b"x" * 1000).status_code == 200


def test_a_password_link_needs_it(client, setup):
    token = setup["make"](password="drop-it")["token"]
    page = client.get(f"/api/fs/shared/{token}", headers={"Accept": "text/html"})
    assert 'id="pw"' in page.text
    assert send(client, token, "a.txt", b"x").status_code == 401
    assert send(client, token, "a.txt", b"x", **{"X-Share-Password": "nope"}).status_code == 401
    assert send(client, token, "a.txt", b"x", **{"X-Share-Password": "drop-it"}).status_code == 200


def test_a_download_link_does_not_take_uploads_and_a_file_cannot_receive(client, setup, auth_headers):
    down = client.post("/api/fs/share-links", json={"path": str(setup["inbox"])}, headers=auth_headers).json()
    assert send(client, down["token"], "a.txt", b"x").status_code == 404
    (setup["inbox"] / "f.txt").write_text("x")
    r = client.post(
        "/api/fs/share-links", json={"path": str(setup["inbox"] / "f.txt"), "kind": "upload"}, headers=auth_headers
    )
    assert r.status_code == 400
    assert send(client, "no-such-token", "a.txt", b"x").status_code == 404


def test_the_link_ends_with_its_maker_and_with_its_expiry(client, setup, monkeypatch):
    import secrets

    from backend.api.files import share_links

    name = f"ul{secrets.token_hex(3)}"
    user = create_user(name, name, "GoodPass123!", role_id="storage_admin")
    tok = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"}).json()["token"]
    r = client.post(
        "/api/fs/share-links",
        json={"path": str(setup["inbox"]), "kind": "upload"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert send(client, token, "a.txt", b"x").status_code == 200
    update_user_profile(user["id"], status="disabled")
    assert send(client, token, "b.txt", b"x").status_code == 410
    links = share_links._load_share_links()
    links[token]["expires_at"] = 1
    share_links._save_share_links(links)
    assert send(client, token, "c.txt", b"x").status_code == 410
    assert client.get(f"/api/fs/shared/{token}").status_code == 410


def test_counts_and_the_activity_log(client, setup, monkeypatch):
    from backend.api.files import share_links

    noted = []
    monkeypatch.setattr(upload_links, "note", lambda item, name, size, ip: noted.append((name, size)))
    token = setup["make"]()["token"]
    send(client, token, "a.txt", b"12345")
    item = share_links._load_share_links()[token]
    assert (item["received_count"], item["received_bytes"]) == (1, 5) and noted == [("a.txt", 5)]


def test_the_page_script_is_the_one_its_policy_allows():
    html = upload_links.page("tok", {"label": "x"}).body.decode()
    script = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    import base64
    import hashlib

    assert base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() == upload_links._SCRIPT_HASH


def test_a_stopped_upload_leaves_nothing(tmp_path):
    import asyncio

    class Req:
        headers = {"content-length": "10", "x-file-name": "a.txt"}

        async def stream(self):
            yield b"12345"  # the sender went away halfway

    with pytest.raises(Exception, match="stopped before the end"):
        asyncio.run(upload_links.receive({}, str(tmp_path), Req()))
    assert list(tmp_path.iterdir()) == []
