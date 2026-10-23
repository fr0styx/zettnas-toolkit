"""Request bodies without a Content-Length get the same size limit (audit pass 2)."""

from backend import config


def _chunks(total_mb):
    yield b'{"password": "'
    for _ in range(total_mb):
        yield b"a" * (1024 * 1024)
    yield b'"}'


def test_chunked_body_over_the_limit_is_refused(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 2 * 1024 * 1024)
    r = client.post("/api/auth/login", content=_chunks(3), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_small_chunked_body_still_works(client):
    r = client.post(
        "/api/auth/login", content=iter([b'{"password": "wrong-pass-1"}']), headers={"content-type": "application/json"}
    )
    assert r.status_code == 401


def test_upload_routes_keep_their_larger_limit():
    from backend.auth import body_limit_for

    assert body_limit_for("/api/fs/upload/chunk") == config.MAX_UPLOAD_BYTES
    assert body_limit_for("/api/v1/auth/login") == config.MAX_BODY_BYTES
