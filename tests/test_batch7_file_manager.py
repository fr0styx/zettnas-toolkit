import os
import time
from unittest.mock import patch
import pytest


def test_fs_search_and_trash_lifecycle(client, auth_headers, tmp_path):
    # Setup test filesystem inside tmp_path
    browse_root = tmp_path / "user"
    browse_root.mkdir(parents=True, exist_ok=True)
    recycle_dir = browse_root / ".RecycleBin"
    recycle_dir.mkdir(parents=True, exist_ok=True)

    # Create dummy files
    (browse_root / "contract_2026.pdf").write_text("dummy contract")
    (browse_root / "tax_report_2026.xlsx").write_text("dummy spreadsheet")
    sub_dir = browse_root / "projects"
    sub_dir.mkdir()
    (sub_dir / "project_alpha_notes.txt").write_text("alpha notes")

    # Create an item in trash
    ts = int(time.time()) - 3600
    trashed_file = recycle_dir / f"{ts}_old_archive.zip"
    trashed_file.write_text("archived data")

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
        # 1. Test search query
        res = client.get("/api/fs/search?q=2026", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        names = [item["name"] for item in data["items"]]
        assert "contract_2026.pdf" in names
        assert "tax_report_2026.xlsx" in names

        # Test search in subfolder
        res_sub = client.get(f"/api/fs/search?q=alpha&path={sub_dir}", headers=auth_headers)
        assert res_sub.status_code == 200
        assert res_sub.json()["total"] == 1
        assert res_sub.json()["items"][0]["name"] == "project_alpha_notes.txt"

        # 2. Test trash listing
        res_trash = client.get("/api/fs/trash", headers=auth_headers)
        assert res_trash.status_code == 200
        trash_data = res_trash.json()
        assert trash_data["total"] >= 1
        assert any(item["name"] == "old_archive.zip" for item in trash_data["items"])

        # 3. Test trash restore
        res_restore = client.post(
            "/api/fs/trash/restore",
            json={"item_id": f"{ts}_old_archive.zip", "target_path": str(sub_dir)},
            headers=auth_headers,
        )
        assert res_restore.status_code == 200
        assert (sub_dir / "old_archive.zip").exists()

        # 4. Put another item in trash and test empty trash
        trashed_temp = recycle_dir / f"{int(time.time())}_temp_delete.txt"
        trashed_temp.write_text("delete me permanently")

        res_empty = client.delete("/api/fs/trash/empty", headers=auth_headers)
        assert res_empty.status_code == 200
        assert res_empty.json()["purged_count"] >= 1
        assert not trashed_temp.exists()
