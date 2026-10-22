import hashlib
import os
import time
from unittest.mock import patch

import pytest

from backend.services.fs_transfer import transfer_manager


def test_browse_enriched_metadata(client, auth_headers, tmp_path):
    root = tmp_path / "browse_test"
    root.mkdir(parents=True, exist_ok=True)
    doc = root / "report.pdf"
    doc.write_text("dummy pdf report")
    sub = root / "subfolder"
    sub.mkdir(parents=True, exist_ok=True)

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        res = client.get(f"/api/browse?path={root}", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["current"] == str(root)
        dirs = {d["name"]: d for d in data["dirs"]}

        assert "report.pdf" in dirs
        assert dirs["report.pdf"]["is_dir"] is False
        assert dirs["report.pdf"]["size"] > 0
        assert "mtime" in dirs["report.pdf"]
        assert "mode" in dirs["report.pdf"]
        assert dirs["report.pdf"]["ext"] == ".pdf"

        assert "subfolder" in dirs
        assert dirs["subfolder"]["is_dir"] is True
        assert dirs["subfolder"]["size"] == 0
        assert "mtime" in dirs["subfolder"]


def test_fs_async_transfer_and_telemetry(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir(parents=True, exist_ok=True)
    src_dir = root / "source"
    src_dir.mkdir(parents=True, exist_ok=True)
    dst_dir = root / "dest"
    dst_dir.mkdir(parents=True, exist_ok=True)

    f1 = src_dir / "file1.txt"
    f1.write_text("Content 1" * 100)
    f2 = src_dir / "file2.txt"
    f2.write_text("Content 2" * 100)

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        # 1. Submit async transfer
        res = client.post(
            "/api/fs/transfer/async",
            json={
                "sources": [str(f1), str(f2)],
                "destination_dir": str(dst_dir),
                "action": "copy",
                "collision_policy": "merge",
            },
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        task_id = data["task_id"]

        # 2. Wait for completion (small files finish in milliseconds)
        for _ in range(50):
            task_info = transfer_manager.get_task(task_id)
            if task_info and task_info["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        task_info = transfer_manager.get_task(task_id)
        assert task_info is not None
        assert task_info["status"] == "completed"
        assert (dst_dir / "file1.txt").exists()
        assert (dst_dir / "file2.txt").exists()

        # 3. List transfers
        res_list = client.get("/api/fs/transfers", headers=auth_headers)
        assert res_list.status_code == 200
        tasks = res_list.json()["tasks"]
        assert any(t["id"] == task_id for t in tasks)

        # 4. Clear completed
        res_clear = client.delete("/api/fs/transfers/completed", headers=auth_headers)
        assert res_clear.status_code == 200


def test_fs_archive_create_and_extract_safe(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir(parents=True, exist_ok=True)
    src_dir = root / "to_compress"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "hello.txt").write_text("Hello World!")
    (src_dir / "data.json").write_text('{"status": "ok"}')

    dest_dir = root / "archives"
    dest_dir.mkdir(parents=True, exist_ok=True)

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        # 1. Create zip archive
        res = client.post(
            "/api/fs/archive/create",
            json={
                "sources": [str(src_dir)],
                "destination_dir": str(dest_dir),
                "archive_name": "bundle.zip",
                "format": "zip",
            },
            headers=auth_headers,
        )
        assert res.status_code == 200
        task_id = res.json()["task_id"]

        for _ in range(50):
            t = transfer_manager.get_task(task_id)
            if t and t["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        archive_file = dest_dir / "bundle.zip"
        assert archive_file.exists()

        # 2. Extract archive into extract_dir
        extract_dir = root / "extracted"
        res_ext = client.post(
            "/api/fs/archive/extract",
            json={
                "archive_path": str(archive_file),
                "destination_dir": str(extract_dir),
            },
            headers=auth_headers,
        )
        assert res_ext.status_code == 200
        ext_task_id = res_ext.json()["task_id"]

        for _ in range(50):
            t = transfer_manager.get_task(ext_task_id)
            if t and t["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)

        assert (extract_dir / "to_compress" / "hello.txt").exists()
        assert (extract_dir / "to_compress" / "hello.txt").read_text() == "Hello World!"


def test_fs_checksum_streaming(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir(parents=True, exist_ok=True)
    sample_file = root / "hash_target.bin"
    raw_bytes = b"ZettNAS SOTA File Explorer Checksum Verification 2026" * 50
    sample_file.write_bytes(raw_bytes)
    expected_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    expected_md5 = hashlib.md5(raw_bytes).hexdigest()

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        # SHA256
        res_sha = client.post(
            "/api/fs/checksum",
            json={"path": str(sample_file), "algorithm": "sha256"},
            headers=auth_headers,
        )
        assert res_sha.status_code == 200
        assert res_sha.json()["checksum"] == expected_sha256
        assert res_sha.json()["size"] == len(raw_bytes)

        # MD5
        res_md5 = client.post(
            "/api/fs/checksum",
            json={"path": str(sample_file), "algorithm": "md5"},
            headers=auth_headers,
        )
        assert res_md5.status_code == 200
        assert res_md5.json()["checksum"] == expected_md5


def test_fs_folder_size_and_standby(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir(parents=True, exist_ok=True)
    folder = root / "test_folder"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "item1.txt").write_text("A" * 1024)
    (folder / "item2.txt").write_text("B" * 2048)

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        # 1. Normal folder size
        res = client.post(
            "/api/fs/folder-size",
            json={"path": str(folder), "force_wake": False},
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["size"] == 3072
        assert data["files_count"] == 2

        # 2. Standby simulation
        with patch("backend.api.fs._FOLDER_SIZE_CACHE", {}):
            with patch("backend.services.rag_engine.is_backing_disk_in_standby", return_value=True):
                res_standby = client.post(
                    "/api/fs/folder-size",
                    json={"path": str(folder), "force_wake": False},
                    headers=auth_headers,
                )
                assert res_standby.status_code == 200
                standby_data = res_standby.json()
                assert standby_data["status"] == "standby"
                assert standby_data["is_standby"] is True
                assert standby_data["size"] is None


def test_fs_permissions_endpoints(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "perm_file.txt"
    target.write_text("Permissions check")

    with patch("backend.api.system.ALLOWED_BROWSE_ROOTS", [str(root)]):
        # 1. Get permissions
        res = client.get(f"/api/fs/permissions?path={target}", headers=auth_headers)
        assert res.status_code == 200
        pdata = res.json()
        assert pdata["status"] == "ok"
        assert "mode_octal" in pdata
        assert "mode_human" in pdata

        # 2. Update permissions (chmod 0640)
        res_upd = client.put(
            "/api/fs/permissions",
            json={"path": str(target), "mode_octal": "0640"},
            headers=auth_headers,
        )
        assert res_upd.status_code == 200
        assert res_upd.json()["status"] == "ok"

        # Verify mode updated
        res_after = client.get(f"/api/fs/permissions?path={target}", headers=auth_headers)
        assert res_after.json()["mode_octal"] == "0640"

        # 3. Guard against system directories (/boot, /appdata)
        res_guarded = client.put(
            "/api/fs/permissions",
            json={"path": "/boot/config/test.cfg", "mode_octal": "0777"},
            headers=auth_headers,
        )
        assert res_guarded.status_code in (403, 404)
