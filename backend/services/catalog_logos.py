"""App catalog logos through ZettNAS (SEC-38).

The catalog's logos live on cdn.jsdelivr.net (the dashboard-icons set) and, for some catalog
sources, on raw.githubusercontent.com. The browser used to load them from there, so opening
the catalog told those services which apps someone was looking at. Now the browser asks
ZettNAS (/api/docker/catalog/logo), which fetches each logo once, keeps it in DATA_DIR, and
serves the copy. Only those two hosts, https, and raster images up to 512 KB; anything else
gets no logo and the card shows the category's icon instead.
"""

from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from backend.config import DATA_DIR, logger

LOGO_HOSTS = ("cdn.jsdelivr.net", "raw.githubusercontent.com")
MAX_BYTES = 512 * 1024
TIMEOUT = 8.0
MISS_SECS = 24 * 3600  # a logo that couldn't be fetched isn't asked for again for a day
TYPES = {  # what the server says it is -> the bytes it must start with
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": b"GIF8",
    "image/webp": b"RIFF",
}


def cache_dir() -> str:
    return os.path.join(DATA_DIR, "cache", "logos")


def allowed(url: str) -> bool:
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (
        u.scheme == "https"
        and (u.hostname or "") in LOGO_HOSTS
        and u.port in (None, 443)
        and not u.username
        and not u.password
        and ".." not in u.path
    )


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102 (urllib's hook)
        if not allowed(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect off the logo hosts", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str) -> tuple[bytes, str]:
    """The logo's bytes and media type, from one of the logo hosts only."""
    opener = urllib.request.build_opener(_SameHostRedirects)
    req = urllib.request.Request(url, headers={"User-Agent": "ZettNAS-catalog/1.0", "Accept": "image/*"})
    with opener.open(req, timeout=TIMEOUT) as r:  # noqa: S310 (https to LOGO_HOSTS only, checked above)
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        data = r.read(MAX_BYTES + 1)
    return data, ctype


def _write(path: str, data: bytes) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _valid(data: bytes, ctype: str) -> bool:
    magic = TYPES.get(ctype)
    return bool(magic) and len(data) <= MAX_BYTES and data.startswith(magic)


def logo(url: str, fetcher: Callable[[str], tuple[bytes, str]] | None = None) -> tuple[bytes, str] | None:
    """The cached logo for url (fetched the first time), or None when there is none to show."""
    fetcher = fetcher or fetch
    if not allowed(url):
        return None
    key = hashlib.sha256(url.encode()).hexdigest()[:40]
    base = os.path.join(cache_dir(), key)
    for ctype in TYPES:
        path = f"{base}.{ctype.split('/')[1]}"
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read(), ctype
    miss = base + ".miss"
    if os.path.exists(miss) and time.time() - os.path.getmtime(miss) < MISS_SECS:
        return None
    os.makedirs(cache_dir(), exist_ok=True)
    try:
        data, ctype = fetcher(url)
    except Exception as e:
        logger.debug(f"catalog logo not fetched: {type(e).__name__}")
        data, ctype = b"", ""
    if not _valid(data, ctype):
        with open(miss, "w", encoding="utf-8"):
            pass
        return None
    _write(f"{base}.{ctype.split('/')[1]}", data)
    return data, ctype
