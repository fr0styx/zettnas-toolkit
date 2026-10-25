"""Docker image references: "registry:port/org/repo:tag@sha256:digest" and every shorter form.

Built-in catalog apps install pinned to the digest that shipped with this ZettNAS version
(catalog_digests.json, refreshed at release time by scripts/pin_catalog_images.py)."""

import json
import os
import re
from functools import lru_cache

# set on containers ZettNAS pinned at install: their updates follow the tag and re-pin
FOLLOW_TAG_LABEL = "zettnas.image.follow-tag"
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_LOCK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog_digests.json")


def split_ref(image: str) -> tuple[str, str, str, str]:
    """(registry, repository, tag, digest). "nginx" -> ("docker.io", "library/nginx", "latest", "")."""
    ref = image.strip()
    digest = ""
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    tag = ""
    last = ref.rsplit("/", 1)[-1]
    if ":" in last:
        ref, tag = ref.rsplit(":", 1)
    parts = ref.split("/", 1)
    if len(parts) == 2 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        registry, repo = parts
    else:
        registry, repo = "docker.io", ref if "/" in ref else f"library/{ref}"
    if registry == "index.docker.io":
        registry = "docker.io"
    return registry, repo, tag or "latest", digest


def name_and_tag(image: str) -> str:
    """The reference without its digest ("nginx:1@sha256:..." -> "nginx:1")."""
    return image.strip().split("@", 1)[0]


def pull_params(image: str) -> tuple[str, str]:
    """fromImage and tag for POST /images/create; a digest is pulled as the tag."""
    ref = image.strip()
    name = name_and_tag(ref)
    _, _, tag, digest = split_ref(ref)
    last = name.rsplit("/", 1)[-1]
    repo = name.rsplit(":", 1)[0] if ":" in last else name
    return repo, (digest or tag)


def with_digest(image: str, digest: str) -> str:
    return f"{name_and_tag(image)}@{digest}" if DIGEST_RE.match(digest or "") else image


@lru_cache(maxsize=1)
def _lock() -> dict[str, str]:
    try:
        with open(_LOCK, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return (
        {k: v for k, v in data.items() if isinstance(v, str) and DIGEST_RE.match(v)} if isinstance(data, dict) else {}
    )


def pinned(image: str) -> str:
    """The catalog image at the digest that shipped with this version (unchanged when unknown)."""
    if not image or "@" in image:
        return image
    digest = _lock().get(image.strip())
    return with_digest(image, digest) if digest else image


def pin_app(app: dict) -> dict:
    """A copy of a built-in catalog app with its images (and its companions') pinned."""
    out = dict(app)
    if out.get("image"):
        out["image"] = pinned(out["image"])
    stack = out.get("stack_services")
    if isinstance(stack, dict):
        out["stack_services"] = {
            k: ({**v, "image": pinned(v["image"])} if isinstance(v, dict) and v.get("image") else v)
            for k, v in stack.items()
        }
    return out
