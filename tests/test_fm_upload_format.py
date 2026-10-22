"""The explorer's upload format: folder and name in the query, the file as the body."""

import os


def test_upload_with_query_and_raw_body(client, auth_headers, paths):
    d = os.path.join(paths["pool"], "uploads-q")
    os.makedirs(d, exist_ok=True)
    r = client.post(
        "/api/fs/upload",
        params={"path": d, "filename": "holiday photo.jpg"},
        content=b"JPEGDATA",
        headers={**auth_headers, "Content-Type": "image/jpeg"},
    )
    assert r.status_code == 200, r.text
    with open(os.path.join(d, "holiday photo.jpg"), "rb") as f:
        assert f.read() == b"JPEGDATA"
