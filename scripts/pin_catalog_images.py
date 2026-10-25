"""Resolves every built-in catalog image to the digest its tag points at today and writes
backend/services/catalog_digests.json. Run at release time: apps then install the exact image
that shipped (and soaked) with that ZettNAS version; updates still follow the tag.

    python scripts/pin_catalog_images.py            # refresh every entry
    python scripts/pin_catalog_images.py --missing  # only images without an entry
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.catalog_templates import CURATED_APP_CATALOG  # noqa: E402
from backend.services.image_ref import split_ref  # noqa: E402

LOCK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "services", "catalog_digests.json"
)
ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def catalog_images() -> list[str]:
    out = set()
    for app in CURATED_APP_CATALOG:
        if app.get("image"):
            out.add(app["image"])
        for svc in (app.get("stack_services") or {}).values():
            if isinstance(svc, dict) and svc.get("image"):
                out.add(svc["image"])
    return sorted(out)


def _token(challenge: str) -> str | None:
    """Anonymous bearer token from a registry's WWW-Authenticate challenge."""
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    if "realm" not in fields:
        return None
    query = "&".join(f"{k}={urllib.request.quote(v)}" for k, v in fields.items() if k in ("service", "scope"))
    with urllib.request.urlopen(f"{fields['realm']}?{query}", timeout=20) as r:
        data = json.loads(r.read())
    return data.get("token") or data.get("access_token")


def resolve(image: str) -> str:
    registry, repo, tag, _ = split_ref(image)
    host = "registry-1.docker.io" if registry == "docker.io" else registry
    url = f"https://{host}/v2/{repo}/manifests/{tag}"
    headers = {"Accept": ACCEPT}
    for _ in range(2):
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                digest = r.headers.get("Docker-Content-Digest")
                if not digest:
                    raise RuntimeError("no digest header")
                return digest
        except urllib.error.HTTPError as e:
            if e.code != 401 or "Authorization" in headers:
                raise
            tok = _token(e.headers.get("WWW-Authenticate", ""))
            if not tok:
                raise
            headers["Authorization"] = f"Bearer {tok}"
    raise RuntimeError("unreachable")


def main() -> int:
    only_missing = "--missing" in sys.argv
    try:
        with open(LOCK, encoding="utf-8") as f:
            lock = json.load(f)
    except (OSError, ValueError):
        lock = {}
    images = catalog_images()
    failed = []
    for img in images:
        if only_missing and img in lock:
            continue
        try:
            lock[img] = resolve(img)
            print(f"ok   {img} {lock[img][:19]}")
        except Exception as e:  # noqa: BLE001 - report and carry on
            failed.append(img)
            print(f"FAIL {img}: {e}")
    lock = {k: lock[k] for k in sorted(lock) if k in images}
    with open(LOCK, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2)
        f.write("\n")
    print(f"{len(lock)} of {len(images)} images pinned; {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
