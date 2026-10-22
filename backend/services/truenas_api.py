"""
TrueNAS companion mode (D5): talk to the TrueNAS middleware with an API key instead of
only reading `zpool`.

Set TRUENAS_URL (for example https://truenas.local) and TRUENAS_API_KEY (TrueNAS:
your user menu → API Keys). ZettNAS then lists pools, datasets and SMB/NFS shares
through the API, and can take ZFS snapshots, which the ransomware guard uses. It
never changes pools or shares. TRUENAS_VERIFY_TLS=0 accepts the self-signed
certificate TrueNAS ships with.
"""

import os
import re
from typing import Any

import httpx

from backend.config import logger


class TrueNASError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("TRUENAS_URL") and os.environ.get("TRUENAS_API_KEY"))


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    base = os.environ.get("TRUENAS_URL", "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise TrueNASError("TRUENAS_URL must start with http:// or https://")
    return httpx.Client(
        base_url=f"{base}/api/v2.0",
        headers={"Authorization": f"Bearer {os.environ.get('TRUENAS_API_KEY', '')}"},
        timeout=15,
        verify=os.environ.get("TRUENAS_VERIFY_TLS", "1") != "0",
        transport=transport,
    )


def _get(path: str, transport=None) -> Any:
    with _client(transport) as c:
        r = c.get(path)
    if r.status_code == 401:
        raise TrueNASError("TrueNAS refused the API key")
    r.raise_for_status()
    return r.json()


def pools(transport=None) -> list[dict[str, Any]]:
    return [
        {
            "name": p.get("name"),
            "status": p.get("status"),
            "healthy": bool(p.get("healthy")),
            "size": p.get("size"),
            "allocated": p.get("allocated"),
            "free": p.get("free"),
        }
        for p in _get("/pool", transport)
    ]


def datasets(transport=None) -> list[dict[str, Any]]:
    out = []
    for d in _get("/pool/dataset?limit=500", transport):
        if d.get("type") != "FILESYSTEM":
            continue
        out.append({"id": d.get("id"), "pool": d.get("pool"), "mountpoint": d.get("mountpoint")})
    return out


def shares(transport=None) -> list[dict[str, Any]]:
    out = [
        {"protocol": "smb", "name": s.get("name"), "path": s.get("path"), "enabled": s.get("enabled", True)}
        for s in _get("/sharing/smb", transport)
    ]
    out += [
        {
            "protocol": "nfs",
            "name": s.get("path") or (s.get("paths") or [""])[0],
            "path": s.get("path") or (s.get("paths") or [""])[0],
            "enabled": s.get("enabled", True),
        }
        for s in _get("/sharing/nfs", transport)
    ]
    return out


def create_snapshot(dataset: str, name: str, recursive: bool = True, transport=None) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", name):
        raise TrueNASError("Invalid snapshot name")
    with _client(transport) as c:
        r = c.post("/zfs/snapshot", json={"dataset": dataset, "name": name, "recursive": recursive})
    if r.status_code not in (200, 201):
        raise TrueNASError(f"Snapshot failed ({r.status_code}): {r.text[:200]}")
    logger.info(f"[TrueNAS] Snapshot {dataset}@{name} created")
    return {"success": True, "snapshot": f"{dataset}@{name}"}
