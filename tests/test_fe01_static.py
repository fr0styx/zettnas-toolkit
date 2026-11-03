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


def test_a_compressed_copy_is_revalidated_with_304(tmp_path):
    client, _ = _app(tmp_path)
    (tmp_path / "sprite.svg").write_text("<svg>" + "<symbol/>" * 300 + "</svg>")
    (tmp_path / "sprite.svg.br").write_bytes(b"BR-SPRITE")
    first = client.get("/sprite.svg", headers={"Accept-Encoding": "br"})
    tag = first.headers["etag"]
    assert first.status_code == 200 and first.content == b"BR-SPRITE" and tag.endswith('-br"')
    again = client.get("/sprite.svg", headers={"Accept-Encoding": "br", "If-None-Match": tag})
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == tag and again.headers["cache-control"] == "no-cache"
    assert again.headers["vary"] == "Accept-Encoding"
    stale = client.get("/sprite.svg", headers={"Accept-Encoding": "br", "If-None-Match": '"old-br"'})
    assert stale.status_code == 200 and stale.content == b"BR-SPRITE"
    plain = client.get("/sprite.svg", headers={"Accept-Encoding": "identity"})
    assert plain.status_code == 200 and "content-encoding" not in plain.headers
    again_plain = client.get(
        "/sprite.svg", headers={"Accept-Encoding": "identity", "If-None-Match": plain.headers["etag"]}
    )
    assert again_plain.status_code == 304
