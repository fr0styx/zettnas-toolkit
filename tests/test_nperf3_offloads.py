"""NPERF-3: the block-list is read at most once a second and never written on a request; a big
JSON answer is compressed off the event loop; chunked uploads are joined in a thread."""

import asyncio
import gzip
import hashlib
import json
import time

import pytest

from backend import auth
from backend.api.files import uploads
from backend.services import ip_block


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "blocks.json"
    monkeypatch.setattr(ip_block, "STORE", str(path))
    monkeypatch.setitem(ip_block._cache, "loaded", False)
    monkeypatch.setitem(ip_block._cache, "checked", 0.0)
    return path


def test_the_block_list_is_looked_at_once_a_second(store, monkeypatch):
    store.write_text(json.dumps({"203.0.113.9": {"until": None}}))
    assert ip_block.is_blocked("203.0.113.9")
    store.write_text("{}")
    assert ip_block.is_blocked("203.0.113.9")  # within the second: the cached copy
    monkeypatch.setitem(ip_block._cache, "checked", time.monotonic() - 2)
    assert not ip_block.is_blocked("203.0.113.9")


def test_an_expired_block_is_not_written_on_a_request(store):
    store.write_text(json.dumps({"203.0.113.7": {"until": time.time() - 5}, "203.0.113.8": {"until": None}}))
    before = store.stat().st_mtime_ns
    assert not ip_block.is_blocked("203.0.113.7")
    assert store.stat().st_mtime_ns == before
    ip_block.block("203.0.113.10", "test")  # the next change drops it
    assert set(json.loads(store.read_text())) == {"203.0.113.8", "203.0.113.10"}


def test_a_big_answer_is_compressed_in_a_thread(monkeypatch):
    big = json.dumps({"x": "y" * (auth.GZIP_IN_THREAD + 10)}).encode()
    used = []
    real = asyncio.to_thread

    async def spy(fn, *a, **k):
        used.append(fn)
        return await real(fn, *a, **k)

    monkeypatch.setattr(auth.asyncio, "to_thread", spy)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": big})

    sent = []

    async def send(m):
        sent.append(m)

    scope = {"type": "http", "method": "GET", "headers": [(b"accept-encoding", b"gzip")]}
    asyncio.run(auth.JsonGzip(app)(scope, None, send))
    assert used == [gzip.compress]
    assert gzip.decompress(sent[1]["body"]) == big


def test_chunks_are_joined_and_hashed(tmp_path):
    parts = []
    for i, data in enumerate((b"abc", b"def")):
        p = tmp_path / f"chunk_{i:06d}"
        p.write_bytes(data)
        parts.append(str(p))
    out = tmp_path / "whole"
    assert uploads._assemble(parts, str(out)) == hashlib.sha256(b"abcdef").hexdigest()
    assert out.read_bytes() == b"abcdef"
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        uploads._assemble([str(tmp_path / "missing")], str(out))
