"""FE-01: compressed copies are served when accepted, and hashed assets are cached as immutable."""

import gzip

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.static_files import IMMUTABLE, CompressedStaticFiles, accepted_encodings


def _app(tmp_path):
    (tmp_path / "assets").mkdir()
    js = b"console.log('hello');" * 200
    (tmp_path / "assets" / "app-abc123.js").write_bytes(js)
    (tmp_path / "assets" / "app-abc123.js.gz").write_bytes(gzip.compress(js))
    (tmp_path / "assets" / "app-abc123.js.br").write_bytes(b"BROTLI")
    (tmp_path / "manifest.json").write_text("{}")
    app = FastAPI()
    app.mount("/", CompressedStaticFiles(directory=str(tmp_path), html=True), name="static")
    return TestClient(app), js


def test_brotli_preferred_then_gzip_then_plain(tmp_path):
    client, js = _app(tmp_path)
    r = client.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip, br"})
    assert r.headers["content-encoding"] == "br" and r.content == b"BROTLI"
    assert r.headers["cache-control"] == IMMUTABLE and "javascript" in r.headers["content-type"]
    r = client.get("/assets/app-abc123.js", headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip" and r.content == js  # client decodes gzip
    r = client.get("/assets/app-abc123.js", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers and r.content == js
    assert r.headers["vary"] == "Accept-Encoding"


def test_non_hashed_files_revalidate(tmp_path):
    client, _ = _app(tmp_path)
    r = client.get("/manifest.json")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_q_zero_means_not_accepted():
    assert accepted_encodings("br;q=0, gzip") == {"gzip"}
