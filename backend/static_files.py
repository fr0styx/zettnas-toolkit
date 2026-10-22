"""Static file serving with precompressed copies and long-lived caching (FE-01).

The build writes name.br and name.gz next to each text asset. When the browser accepts
Brotli or gzip, that copy is sent with Content-Encoding. Files under /assets/ have content
hashes in their names, so they are cached for a year as immutable; everything else is
revalidated.
"""

import os
from typing import Optional, Tuple

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"

_ENCODINGS = (("br", ".br"), ("gzip", ".gz"))


def accepted_encodings(accept_encoding: str) -> set:
    out = set()
    for part in (accept_encoding or "").lower().split(","):
        name, _, params = part.strip().partition(";")
        if params.strip().replace(" ", "") in ("q=0", "q=0.0", "q=0.00", "q=0.000"):
            continue
        if name:
            out.add(name.strip())
    return out


def pick_precompressed(full_path: str, accept_encoding: str) -> Optional[Tuple[str, str]]:
    """(compressed path, encoding) for the best precompressed copy the client accepts."""
    ok = accepted_encodings(accept_encoding)
    for enc, suffix in _ENCODINGS:
        if enc in ok and os.path.isfile(full_path + suffix):
            return full_path + suffix, enc
    return None


class CompressedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code not in (200, 304):
            return response
        norm = path.replace("\\", "/").lstrip("/")
        response.headers["Cache-Control"] = IMMUTABLE if norm.startswith("assets/") else REVALIDATE
        if response.status_code != 200:
            return response
        headers = dict((k.decode().lower(), v.decode()) for k, v in scope.get("headers", []))
        if "range" in headers:
            return response
        full_path, _ = self.lookup_path(path)
        if not full_path:
            return response
        picked = pick_precompressed(full_path, headers.get("accept-encoding", ""))
        if not picked:
            response.headers["Vary"] = "Accept-Encoding"
            return response
        comp_path, enc = picked
        compressed = self.file_response(comp_path, os.stat(comp_path), scope)
        compressed.headers["Content-Type"] = response.headers.get("content-type", "application/octet-stream")
        compressed.headers["Content-Encoding"] = enc
        compressed.headers["Vary"] = "Accept-Encoding"
        compressed.headers["Cache-Control"] = response.headers["Cache-Control"]
        if "etag" in response.headers:
            compressed.headers["ETag"] = response.headers["etag"].rstrip('"') + f'-{enc}"'
        return compressed
