"""SEC-38: the browser gets catalog logos from ZettNAS, and every outside host the code can
contact is listed in docs/PRIVACY.md (or is only a link, an example or a namespace)."""

import glob
import os
import re

import pytest

from backend.services import catalog_logos

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
ICON = "https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/jellyfin.png"


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(catalog_logos, "cache_dir", lambda: str(tmp_path))
    return tmp_path


@pytest.mark.parametrize(
    "url,ok",
    [
        (ICON, True),
        ("https://raw.githubusercontent.com/a/b/main/logo.png", True),
        ("http://cdn.jsdelivr.net/x.png", False),
        ("https://evil.example/x.png", False),
        ("https://cdn.jsdelivr.net.evil.example/x.png", False),
        ("https://user:pw@cdn.jsdelivr.net/x.png", False),
        ("https://cdn.jsdelivr.net:8443/x.png", False),
        ("https://cdn.jsdelivr.net/../x.png", False),
        ("not a url", False),
    ],
)
def test_only_the_logo_hosts(url, ok):
    assert catalog_logos.allowed(url) is ok


def test_fetched_once_then_served_from_the_cache(cache):
    calls = []

    def fetcher(url):
        calls.append(url)
        return PNG, "image/png"

    assert catalog_logos.logo(ICON, fetcher) == (PNG, "image/png")
    assert catalog_logos.logo(ICON, fetcher) == (PNG, "image/png")
    assert len(calls) == 1
    assert any(name.endswith(".png") for name in os.listdir(cache))


@pytest.mark.parametrize(
    "data,ctype",
    [
        (b"<svg onload=alert(1)>", "image/svg+xml"),  # SVG can carry script: never served
        (b"<html>", "text/html"),
        (b"GIF8" + b"x" * 10, "image/png"),  # says PNG, isn't
        (b"\x89PNG\r\n\x1a\n" + b"x" * catalog_logos.MAX_BYTES, "image/png"),  # too big
    ],
)
def test_anything_but_a_small_raster_image_is_refused(cache, data, ctype):
    calls = []

    def fetcher(url):
        calls.append(url)
        return data, ctype

    assert catalog_logos.logo(ICON, fetcher) is None
    assert catalog_logos.logo(ICON, fetcher) is None  # and not asked again for a day
    assert len(calls) == 1


def test_a_host_outside_the_list_is_never_asked(cache):
    def fetcher(url):
        raise AssertionError("fetched")

    assert catalog_logos.logo("https://tracker.example/logo.png", fetcher) is None


def test_the_route(cache, monkeypatch, client, auth_headers):
    monkeypatch.setattr(catalog_logos, "fetch", lambda url: (PNG, "image/png"))
    headers = auth_headers
    r = client.get("/api/docker/catalog/logo", params={"url": ICON}, headers=headers)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (
        client.get(
            "/api/docker/catalog/logo", params={"url": "https://evil.example/x.png"}, headers=headers
        ).status_code
        == 404
    )


# Hosts in the code that ZettNAS never contacts by itself: links people may click, documentation,
# XML namespaces, examples and placeholders, and addresses on the person's own network.
NOT_CONTACTED = {
    "in-toto.io",  # identifiers in signed statements, not addresses
    "sigstore.dev",
    "www.w3.org",
    "schemas.openxmlformats.org",
    "example.com",
    "nas.example.com",
    "auth.example.com",
    "nextcloud.example.com",
    "rclone.org",
    "restic.net",
    "caddyserver.com",
    "selfh.st",
    "www.ubuntu.com",
    "www.openstreetmap.org",
    "host.docker.internal",
    "hooks.slack.com",
    "s3.us-west-000.backblazeb2.com",
    "discord.com",
    "calendar.google.com",
    "token.actions.githubusercontent.com",
    "graph.microsoft.com",
}


def _hosts():
    files = glob.glob(os.path.join(ROOT, "backend", "**", "*.py"), recursive=True)
    files += [
        f
        for f in glob.glob(os.path.join(ROOT, "frontend", "src", "**", "*.*"), recursive=True)
        if f.endswith((".js", ".html")) and "__tests__" not in f and os.sep + "locales" + os.sep not in f
    ]
    files.append(os.path.join(ROOT, "frontend", "index.html"))
    found = {}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for m in re.finditer(r"https?://([a-zA-Z0-9.-]+\.[a-z]{2,})", fh.read()):
                found.setdefault(m.group(1).lower(), os.path.relpath(f, ROOT))
    return found


def test_every_outside_host_is_in_the_privacy_doc():
    with open(os.path.join(ROOT, "docs", "PRIVACY.md"), encoding="utf-8") as f:
        privacy = f.read().lower()
    own_network = (".local", ".lan", ".internal", ".home.arpa")
    undocumented = {
        h: f for h, f in _hosts().items() if h not in NOT_CONTACTED and not h.endswith(own_network) and h not in privacy
    }
    assert not undocumented, (
        "these hosts can be contacted but docs/PRIVACY.md doesn't say when; add them to its table "
        f"(or to NOT_CONTACTED if the code only links to them): {undocumented}"
    )
