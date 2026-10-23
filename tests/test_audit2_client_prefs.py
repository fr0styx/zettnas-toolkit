"""The shared client preferences file is written by admins only (audit pass 2)."""

import secrets

from backend.users_db import create_user


def test_only_admins_write_shared_preferences(client, auth_headers):
    name = f"cp{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="share_user")
    token = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"}).json()["token"]
    user = {"Authorization": f"Bearer {token}"}
    assert client.post("/api/system/client-preferences", headers=user, json={"zettnas_x": "1"}).status_code == 403
    assert (
        client.post("/api/system/client-preferences", headers=auth_headers, json={"lcd_theme": "dark"}).status_code
        == 200
    )
    assert "zettnas_x" not in client.get("/api/system/client-preferences", headers=user).json()["preferences"]
