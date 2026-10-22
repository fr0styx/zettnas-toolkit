import io
import os
from unittest.mock import patch

import pytest

import backend.api.fs as fs_mod


@pytest.fixture
def fs_sandbox(tmp_path, pool_tree):
    links_file = str(tmp_path / "shared_links.json")
    test_dir = os.path.join(pool_tree, "media")

    with (
        patch.object(fs_mod, "SHARE_LINKS_FILE", links_file),
        patch.object(fs_mod, "ALLOWED_BROWSE_ROOTS", [str(pool_tree)]),
    ):
        yield {
            "links_file": links_file,
            "test_dir": test_dir,
            "pool_tree": pool_tree,
        }


def test_chunked_upload_pipeline_success(client, auth_headers, fs_sandbox):
    test_dir = fs_sandbox["test_dir"]
    target_filename = "assembled_file.bin"
    chunk1 = b"AAAA" * 1024  # 4KB
    chunk2 = b"BBBB" * 1024  # 4KB
    total_data = chunk1 + chunk2

    import hashlib

    expected_sha = hashlib.sha256(total_data).hexdigest()

    # 1. Init upload
    init_res = client.post(
        "/api/fs/upload/init",
        json={
            "path": test_dir,
            "filename": target_filename,
            "total_size": len(total_data),
            "total_chunks": 2,
        },
        headers=auth_headers,
    )
    assert init_res.status_code == 200, init_res.text
    init_data = init_res.json()
    upload_id = init_data["upload_id"]

    # 2. Upload chunk 0
    res_c0 = client.post(
        f"/api/fs/upload/chunk?upload_id={upload_id}&chunk_index=0",
        content=chunk1,
        headers=auth_headers,
    )
    assert res_c0.status_code == 200, res_c0.text

    # 3. Upload chunk 1
    res_c1 = client.post(
        f"/api/fs/upload/chunk?upload_id={upload_id}&chunk_index=1",
        content=chunk2,
        headers=auth_headers,
    )
    assert res_c1.status_code == 200, res_c1.text

    # 4. Complete upload with SHA-256 validation
    comp_res = client.post(
        "/api/fs/upload/complete",
        json={
            "upload_id": upload_id,
            "expected_sha256": expected_sha,
        },
        headers=auth_headers,
    )
    assert comp_res.status_code == 200, comp_res.text
    comp_data = comp_res.json()
    assert comp_data["status"] == "ok"
    assert comp_data["size_bytes"] == len(total_data)
    assert comp_data["sha256"] == expected_sha

    # Verify file content on disk
    dest_path = os.path.join(test_dir, target_filename)
    assert os.path.isfile(dest_path)
    with open(dest_path, "rb") as f:
        assert f.read() == total_data


def test_chunked_upload_sha256_mismatch_fails_and_cleans_up(client, auth_headers, fs_sandbox):
    test_dir = fs_sandbox["test_dir"]
    target_filename = "corrupt_file.bin"
    chunk = b"VALID_BYTES"

    init_res = client.post(
        "/api/fs/upload/init",
        json={
            "path": test_dir,
            "filename": target_filename,
            "total_size": len(chunk),
            "total_chunks": 1,
        },
        headers=auth_headers,
    )
    assert init_res.status_code == 200
    upload_id = init_res.json()["upload_id"]

    client.post(
        f"/api/fs/upload/chunk?upload_id={upload_id}&chunk_index=0",
        content=chunk,
        headers=auth_headers,
    )

    # Complete with wrong sha256
    comp_res = client.post(
        "/api/fs/upload/complete",
        json={
            "upload_id": upload_id,
            "expected_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        },
        headers=auth_headers,
    )
    assert comp_res.status_code == 400
    assert "SHA-256 integrity mismatch" in comp_res.text

    dest_path = os.path.join(test_dir, target_filename)
    assert not os.path.exists(dest_path)


def test_share_link_rate_limiting(client, auth_headers, fs_sandbox):
    test_file = os.path.join(fs_sandbox["test_dir"], "readme.txt")

    res = client.post(
        "/api/fs/share-links",
        json={
            "path": test_file,
            "password": "CorrectPassword123!",
        },
        headers=auth_headers,
    )
    assert res.status_code == 200
    token = res.json()["token"]

    # Trigger 5 failed password attempts
    for _ in range(5):
        wrong_res = client.get(f"/api/fs/shared/{token}", headers={"X-Share-Password": "WrongPassword"})
        assert wrong_res.status_code == 401

    # 6th attempt should return 429 Too Many Requests
    blocked_res = client.get(f"/api/fs/shared/{token}", headers={"X-Share-Password": "WrongPassword"})
    assert blocked_res.status_code == 429
    assert "Too many failed password attempts" in blocked_res.text

    from backend.api.fs import _SHARE_PWD_ATTEMPTS

    _SHARE_PWD_ATTEMPTS.clear()
