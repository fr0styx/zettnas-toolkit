"""Share links follow their creator's access (audit pass 2)."""

import secrets

from backend.users_db import create_user, update_user_profile


def test_link_ends_when_its_creator_is_disabled(client, monkeypatch, tmp_path):
    from backend.api import fs as fs_api

    name = f"sl{secrets.token_hex(3)}"
    home = tmp_path / "pool" / "homes" / name
    home.mkdir(parents=True)
    (home / "doc.txt").write_text("dummy")
    monkeypatch.setattr(fs_api, "ALLOWED_BROWSE_ROOTS", [str(tmp_path / "pool")])
    monkeypatch.setattr("backend.config.POOL_PATH", str(tmp_path / "pool"))
    user = create_user(name, name, "GoodPass123!", role_id="storage_admin")
    tok = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"}).json()["token"]
    r = client.post(
        "/api/fs/share-links", headers={"Authorization": f"Bearer {tok}"}, json={"path": str(home / "doc.txt")}
    )
    assert r.status_code == 200, r.text
    link = r.json().get("token") or r.json()["link"]["token"]
    assert client.get(f"/api/fs/shared/{link}").status_code == 200
    update_user_profile(user["id"], status="disabled")
    assert client.get(f"/api/fs/shared/{link}").status_code == 410
