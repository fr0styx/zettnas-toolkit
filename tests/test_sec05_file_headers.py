"""SEC-05: user files are served so they can't run script in the app's origin."""

from unittest.mock import patch

import pytest


@pytest.mark.parametrize("route", ["/api/fs/stream", "/api/fs/download", "/api/fs/preview/image"])
@pytest.mark.parametrize("name", ["evil.html", "evil.svg"])
def test_active_content_is_sandboxed(client, auth_headers, tmp_path, route, name):
    root = tmp_path / "user"
    root.mkdir()
    f = root / name
    f.write_text("<script>fetch('/api/users')</script>")
    with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]):
        res = client.get(route, params={"path": str(f)}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert "sandbox" in res.headers.get("content-security-policy", "")
    assert res.headers.get("x-content-type-options") == "nosniff"


def test_range_responses_and_pdfs(client, auth_headers, tmp_path):
    root = tmp_path / "user"
    root.mkdir()
    page = root / "page.html"
    page.write_text("<script>1</script>" * 10)
    pdf = root / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    with patch("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)]):
        res = client.get("/api/fs/stream", params={"path": str(page)}, headers={**auth_headers, "Range": "bytes=0-9"})
        assert res.status_code == 206
        assert "sandbox" in res.headers.get("content-security-policy", "")
        res = client.get("/api/fs/stream", params={"path": str(pdf)}, headers=auth_headers)
        assert res.status_code == 200
        assert "content-security-policy" not in res.headers
        assert res.headers.get("x-content-type-options") == "nosniff"
