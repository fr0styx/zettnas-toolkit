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


def test_fs_roots_hierarchy(client, auth_headers, tmp_path):
    user_root = tmp_path / "user"
    user_root.mkdir(parents=True, exist_ok=True)
    cache_pool = tmp_path / "cache"
    cache_pool.mkdir(parents=True, exist_ok=True)
    remotes_dir = tmp_path / "remotes"
    remotes_dir.mkdir(parents=True, exist_ok=True)
    (remotes_dir / "onedrive-test").mkdir(parents=True, exist_ok=True)

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(user_root)]):
        with patch("backend.config.REMOTES_PATH", str(remotes_dir)):
            with patch(
                "os.path.exists",
                side_effect=lambda p: (
                    str(p)
                    in (str(user_root), str(cache_pool), str(remotes_dir), str(remotes_dir / "onedrive-test"), "/boot")
                ),
            ):
                with patch(
                    "os.path.isdir",
                    side_effect=lambda p: (
                        str(p)
                        in (str(user_root), str(cache_pool), str(remotes_dir), str(remotes_dir / "onedrive-test"))
                    ),
                ):
                    with patch(
                        "os.listdir", side_effect=lambda p: ["onedrive-test"] if str(p) == str(remotes_dir) else []
                    ):
                        res = client.get("/api/fs/roots", headers=auth_headers)
                        assert res.status_code == 200
                        data = res.json()
                        assert data["status"] == "ok"
                        assert len(data["roots"]) >= 1
                        assert data["array"] is not None
                        assert any(r["name"] == "onedrive-test" for r in data["remotes"])


def test_freedesktop_trashinfo_lifecycle(client, auth_headers, tmp_path):
    browse_root = tmp_path / "user"
    browse_root.mkdir(parents=True, exist_ok=True)
    docs = browse_root / "docs"
    docs.mkdir()
    sample = docs / "statement.txt"
    sample.write_text("Monthly Financial Statement")

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
        # 1. Delete item using /api/fs/delete
        del_res = client.post("/api/fs/delete", json={"path": str(sample)}, headers=auth_headers)
        assert del_res.status_code == 200
        assert not sample.exists()

        # Check FreeDesktop trash structure
        files_dir = browse_root / ".RecycleBin" / "files"
        info_dir = browse_root / ".RecycleBin" / "info"
        assert files_dir.exists()
        assert info_dir.exists()

        trashed_files = list(files_dir.iterdir())
        assert len(trashed_files) == 1
        item_id = trashed_files[0].name
        assert "statement.txt" in item_id

        trashinfo_file = info_dir / f"{item_id}.trashinfo"
        assert trashinfo_file.exists()
        info_content = trashinfo_file.read_text()
        assert "[Trash Info]" in info_content
        assert f"Path={sample}" in info_content
        assert "DeletionDate=" in info_content

        # 2. Verify trash list endpoint returns original path
        list_res = client.get("/api/fs/trash", headers=auth_headers)
        assert list_res.status_code == 200
        items = list_res.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "statement.txt"
        assert items[0]["original_path"] == str(sample)

        # Remove the original parent directory to test reconstruction
        import shutil

        shutil.rmtree(str(docs))
        assert not docs.exists()

        # 3. Restore without explicit target_path (should reconstruct parent directory)
        restore_res = client.post("/api/fs/trash/restore", json={"item_id": item_id}, headers=auth_headers)
        assert restore_res.status_code == 200
        assert sample.exists()
        assert sample.read_text() == "Monthly Financial Statement"
        assert not trashinfo_file.exists()


def test_fs_preview_redaction_and_hex(client, auth_headers, tmp_path):
    browse_root = tmp_path / "user"
    browse_root.mkdir(parents=True, exist_ok=True)

    # 1. Sensitive text file
    secret_conf = browse_root / "app.env"
    secret_conf.write_text("DB_PASS=SuperSecretPassword123\nAPI_TOKEN=zat_secret1234567890abcdef\nDEBUG=True\n")

    # 2. Binary file
    bin_file = browse_root / "firmware.bin"
    bin_file.write_bytes(bytes(range(64)))

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
        # Preview sensitive config
        res_conf = client.get(f"/api/fs/preview?path={secret_conf}", headers=auth_headers)
        assert res_conf.status_code == 200
        data_conf = res_conf.json()
        assert data_conf["type"] == "text"
        assert "[REDACTED]" in data_conf["content"]
        assert "zat_secret1234567890abcdef" not in data_conf["content"]
        assert "SuperSecretPassword123" not in data_conf["content"]

        # Preview binary file
        res_bin = client.get(f"/api/fs/preview?path={bin_file}", headers=auth_headers)
        assert res_bin.status_code == 200
        data_bin = res_bin.json()
        assert data_bin["type"] == "hex"
        assert len(data_bin["hex_dump"]) >= 1
        assert "00000000" in data_bin["hex_dump"][0]

        # 3. Image file with metadata
        from PIL import Image

        img_file = browse_root / "photo.jpg"
        test_img = Image.new("RGB", (640, 480), color="red")
        test_img.save(img_file, format="JPEG")

        res_img = client.get(f"/api/fs/preview?path={img_file}", headers=auth_headers)
        assert res_img.status_code == 200
        data_img = res_img.json()
        assert data_img["type"] == "image"
        assert data_img["width"] == 640
        assert data_img["height"] == 480
        assert data_img["dimensions"] == "640 × 480"

        # 4. HEIC image preview and transcoding
        heic_file = browse_root / "photo.heic"
        heic_img = Image.new("RGB", (800, 600), color="blue")
        heic_img.save(heic_file, format="HEIF")

        res_heic = client.get(f"/api/fs/preview?path={heic_file}", headers=auth_headers)
        assert res_heic.status_code == 200
        data_heic = res_heic.json()
        assert data_heic["type"] == "image"
        assert data_heic["ext"] == ".heic"
        assert data_heic["dimensions"] == "800 × 600"
        assert data_heic["url"] == f"/api/fs/preview/image?path={heic_file}"
        assert data_heic["download_url"] == f"/api/fs/download?path={heic_file}"

        # Direct image preview transcoding endpoint
        res_preview_img = client.get(f"/api/fs/preview/image?path={heic_file}", headers=auth_headers)
        assert res_preview_img.status_code == 200
        assert res_preview_img.headers["content-type"] == "image/webp"
        assert len(res_preview_img.content) > 100

        # Thumbnail downscaling
        res_thumb = client.get(f"/api/fs/preview/image?path={heic_file}&thumb=1", headers=auth_headers)
        assert res_thumb.status_code == 200
        assert res_thumb.headers["content-type"] == "image/webp"


def test_fs_stream_partial_range(client, auth_headers, tmp_path):
    browse_root = tmp_path / "user"
    browse_root.mkdir(parents=True, exist_ok=True)
    media_file = browse_root / "sample.mp4"
    sample_content = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" * 10
    media_file.write_bytes(sample_content)

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
        # Range request bytes 10-25
        headers = dict(auth_headers)
        headers["Range"] = "bytes=10-25"
        res = client.get(f"/api/fs/stream?path={media_file}", headers=headers)
        assert res.status_code == 206
        assert res.headers.get("Content-Range") == f"bytes 10-25/{len(sample_content)}"
        assert res.content == sample_content[10:26]


def test_fs_download_zip_streaming(client, auth_headers, tmp_path):
    browse_root = tmp_path / "user"
    browse_root.mkdir(parents=True, exist_ok=True)
    file_a = browse_root / "file_a.txt"
    file_b = browse_root / "file_b.txt"
    file_a.write_text("Hello from file A")
    file_b.write_text("Hello from file B")

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(browse_root)]):
        res = client.get(f"/api/fs/download-zip?paths={file_a},{file_b}", headers=auth_headers)
        assert res.status_code == 200
        assert res.headers.get("content-type") == "application/zip"
        import io
        import zipfile

        zf = zipfile.ZipFile(io.BytesIO(res.content))
        namelist = zf.namelist()
        assert "file_a.txt" in namelist
        assert "file_b.txt" in namelist
        assert zf.read("file_a.txt") == b"Hello from file A"


def test_mnt_can_be_declared_and_browsed(client, auth_headers, tmp_path):
    """Verify that when /mnt is declared or allowed, browsing /mnt and sub-pools works cleanly."""
    mnt_dir = tmp_path / "mnt"
    mnt_dir.mkdir(parents=True, exist_ok=True)
    pool1 = mnt_dir / "pool1"
    pool1.mkdir(parents=True, exist_ok=True)
    pool2 = mnt_dir / "pool2"
    pool2.mkdir(parents=True, exist_ok=True)
    test_file = pool1 / "data.txt"
    test_file.write_text("pool1 data")

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(mnt_dir)]):
        # 1. Browse /mnt root
        res = client.get(f"/api/browse?path={mnt_dir}", headers=auth_headers)
        assert res.status_code == 200
        dirs = [d["name"] for d in res.json()["dirs"]]
        assert "pool1" in dirs
        assert "pool2" in dirs

        # 2. Browse /mnt/pool1
        res_pool = client.get(f"/api/browse?path={pool1}", headers=auth_headers)
        assert res_pool.status_code == 200
        pool_files = [f["name"] for f in res_pool.json()["dirs"]]
        assert "data.txt" in pool_files

        # 3. Path escaping outside /mnt is still rejected
        outside = tmp_path / "outside_secret"
        outside.mkdir(parents=True, exist_ok=True)
        res_outside = client.get(f"/api/browse?path={outside}", headers=auth_headers)
        assert res_outside.status_code == 403
