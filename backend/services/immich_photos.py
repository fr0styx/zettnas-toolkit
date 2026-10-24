"""Photo search through Immich when it runs next to ZettNAS (Batch 6, AI-8).

An administrator sets where Immich is; each person connects their own Immich API key, so a
search shows that person's Immich library and nobody else's. Thumbnails are fetched by
ZettNAS (the key never reaches the browser). Without Immich, ZettNAS's own photo captions
and text reading at idle answer photo searches.
"""

import os
import threading
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.config import DATA_DIR, logger
from backend.fsutil import atomic_write_json, read_json

CONFIG_FILE = os.path.join(DATA_DIR, "immich.json")
TIMEOUT = 6.0
_lock = threading.Lock()


class ImmichError(RuntimeError):
    pass


def _cfg() -> dict[str, Any]:
    data = read_json(CONFIG_FILE, {}) or {}
    data.setdefault("keys", {})
    return data


def _save(data: dict[str, Any]) -> None:
    atomic_write_json(CONFIG_FILE, data)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        logger.debug("immich: chmod failed", exc_info=True)


def status(username: str) -> dict[str, Any]:
    c = _cfg()
    return {
        "url": c.get("url") or "",
        "connected": bool(c.get("url") and c["keys"].get(username)),
        "detected": detect(),
    }


def set_url(url: str) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise ValueError("Enter Immich's address, like http://192.168.1.10:2283.")
    clean = f"{u.scheme}://{u.netloc}{u.path.rstrip('/')}"
    with _lock:
        c = _cfg()
        c["url"] = clean
        _save(c)
    return clean


def connect(username: str, api_key: str) -> dict[str, Any]:
    """Checks the key against Immich and stores it for this person."""
    c = _cfg()
    if not c.get("url"):
        raise ValueError("An administrator has to set Immich's address first.")
    key = api_key.strip()
    if len(key) < 20 or len(key) > 200:
        raise ValueError("That doesn't look like an Immich API key.")
    me = _get(c["url"], key, "/api/users/me")
    with _lock:
        c = _cfg()
        c["keys"][username] = key
        _save(c)
    return {"connected": True, "immich_user": me.get("name") or me.get("email") or ""}


def disconnect(username: str) -> bool:
    with _lock:
        c = _cfg()
        found = c["keys"].pop(username, None) is not None
        if found:
            _save(c)
    return found


def _get(base: str, key: str, path: str) -> dict[str, Any]:
    try:
        r = httpx.get(base + path, headers={"x-api-key": key, "Accept": "application/json"}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise ImmichError(f"Immich didn't answer: {e.__class__.__name__}") from None
    if r.status_code in (401, 403):
        raise ImmichError("Immich refused the key.")
    r.raise_for_status()
    return r.json()


def smart_search(username: str, query: str, limit: int = 24) -> list[dict[str, Any]]:
    """This person's Immich photos matching the query ([] when not connected)."""
    c = _cfg()
    key = c["keys"].get(username)
    if not c.get("url") or not key or not query.strip():
        return []
    try:
        r = httpx.post(
            c["url"] + "/api/search/smart",
            headers={"x-api-key": key, "Accept": "application/json"},
            json={"query": query.strip()[:500], "size": max(1, min(int(limit), 100))},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        items = ((r.json() or {}).get("assets") or {}).get("items") or []
    except (httpx.HTTPError, ValueError) as e:
        logger.info(f"[Immich] search failed: {e.__class__.__name__}")
        return []
    out = []
    for a in items[:limit]:
        aid = str(a.get("id") or "")
        if not aid:
            continue
        out.append(
            {
                "id": aid,
                "name": a.get("originalFileName") or "",
                "taken": a.get("localDateTime") or a.get("fileCreatedAt"),
                "thumbnail_url": f"/api/immich/thumbnail/{aid}",
                "immich_url": f"{c['url']}/photos/{aid}",
                "source": "immich",
            }
        )
    return out


def thumbnail(username: str, asset_id: str) -> tuple[bytes, str]:
    if not asset_id or not all(ch.isalnum() or ch == "-" for ch in asset_id) or len(asset_id) > 64:
        raise ValueError("Not an Immich photo.")
    c = _cfg()
    key = c["keys"].get(username)
    if not c.get("url") or not key:
        raise ImmichError("Not connected to Immich.")
    try:
        r = httpx.get(
            f"{c['url']}/api/assets/{asset_id}/thumbnail",
            params={"size": "thumbnail"},
            headers={"x-api-key": key},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise ImmichError(f"Immich didn't answer: {e.__class__.__name__}") from None
    if r.status_code != 200:
        raise ImmichError("Immich has no such photo for you.")
    return r.content, r.headers.get("content-type", "image/jpeg")


def detect() -> str:
    """Immich's address when its server container runs on this host, else ""."""
    try:
        from backend.services.docker_client import request

        st, data = request("GET", "/containers/json")
        if st != 200 or not isinstance(data, list):
            return ""
        for ctr in data:
            if "immich-server" not in str(ctr.get("Image", "")):
                continue
            for p in ctr.get("Ports") or []:
                if p.get("PrivatePort") == 2283 and p.get("PublicPort"):
                    from backend.hardware.network import read_ip

                    return f"http://{read_ip() or 'localhost'}:{p['PublicPort']}"
    except Exception:
        logger.debug("immich: detection failed", exc_info=True)
    return ""
