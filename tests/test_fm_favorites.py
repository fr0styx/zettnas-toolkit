"""File Explorer favorite folders: /api/fs/favorites, kept per user."""

from unittest.mock import patch

import backend.config as config


def test_add_list_remove_favorites(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    (root / "Photos" / "2025").mkdir(parents=True)
    (root / "notes.txt").write_text("x")
    with (
        patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]),
        patch.object(config, "DATA_DIR", str(tmp_path / "data")),
    ):
        (tmp_path / "data").mkdir()
        assert client.get("/api/fs/favorites", headers=auth_headers).json() == {"favorites": []}

        res = client.post("/api/fs/favorites", json={"path": str(root / "Photos" / "2025") + "/"}, headers=auth_headers)
        assert res.status_code == 200
        res = client.post(
            "/api/fs/favorites", json={"path": str(root / "Photos"), "name": "My photos"}, headers=auth_headers
        )
        favs = client.get("/api/fs/favorites", headers=auth_headers).json()["favorites"]
        assert [(f["name"], f["available"]) for f in favs] == [("2025", True), ("My photos", True)]

        # adding again moves it to the end instead of duplicating
        client.post("/api/fs/favorites", json={"path": str(root / "Photos" / "2025")}, headers=auth_headers)
        favs = client.get("/api/fs/favorites", headers=auth_headers).json()["favorites"]
        assert [f["name"] for f in favs] == ["My photos", "2025"]

        # files and places outside the roots are refused
        assert (
            client.post("/api/fs/favorites", json={"path": str(root / "notes.txt")}, headers=auth_headers).status_code
            == 400
        )
        assert client.post("/api/fs/favorites", json={"path": "/etc"}, headers=auth_headers).status_code in (400, 403)

        # a folder that disappears stays listed, marked unavailable
        (root / "Photos" / "2025").rmdir()
        favs = client.get("/api/fs/favorites", headers=auth_headers).json()["favorites"]
        assert [f["available"] for f in favs] == [True, False]

        res = client.delete("/api/fs/favorites", params={"path": str(root / "Photos")}, headers=auth_headers)
        assert [f["name"] for f in res.json()["favorites"]] == ["2025"]
