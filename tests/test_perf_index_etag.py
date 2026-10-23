"""index.html: revalidated with an ETag instead of re-sent on every load (PERF-5)."""

from fastapi.testclient import TestClient

from backend.main import app


def _client(tmp_path, monkeypatch):
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text('<html><body class="studio-workbench">ZettNAS</body></html>')
    monkeypatch.setattr("backend.main.STATIC_DIR", str(static_dir))
    return TestClient(app), static_dir


def test_unchanged_page_answers_304(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch)
    first = client.get("/")
    etag = first.headers["etag"]
    assert first.status_code == 200 and "no-store" not in first.headers["cache-control"]
    again = client.get("/", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""


def test_a_new_build_or_the_lcd_gets_the_page(tmp_path, monkeypatch):
    client, static_dir = _client(tmp_path, monkeypatch)
    etag = client.get("/").headers["etag"]
    lcd = client.get("/?mode=lcd", headers={"If-None-Match": etag})
    assert lcd.status_code == 200 and "lcd-direct" in lcd.text
    (static_dir / "index.html").write_text('<html><body class="studio-workbench">New build</body></html>')
    fresh = client.get("/", headers={"If-None-Match": etag})
    assert fresh.status_code == 200 and "New build" in fresh.text
