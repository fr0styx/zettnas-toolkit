"""
TrueNAS companion mode (D5): talk to the TrueNAS middleware with an API key instead of
only reading `zpool`.

Set TRUENAS_URL (for example https://truenas.local) and TRUENAS_API_KEY (TrueNAS:
your user menu → API Keys). ZettNAS then lists pools, datasets and SMB/NFS shares
through the API, and can take ZFS snapshots, which the ransomware guard uses. It
never changes pools or shares. TRUENAS_VERIFY_TLS=0 accepts the self-signed
certificate TrueNAS ships with.

TrueNAS 25.04 added a JSON-RPC 2.0 API over a WebSocket (/api/current) and TrueNAS 27 removed
the REST API; when REST answers 404, 405 or 410 the same calls go over JSON-RPC.
"""

import json
import os
import re
import ssl
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


REST_GONE = (404, 405, 410)  # TrueNAS 27 has no /api/v2.0


class _RestGone(Exception):
    pass


def _get(path: str, transport=None) -> Any:
    with _client(transport) as c:
        r = c.get(path)
    if r.status_code == 401:
        raise TrueNASError("TrueNAS refused the API key")
    if r.status_code in REST_GONE:
        raise _RestGone(path)
    r.raise_for_status()
    return r.json()


def _open_ws(url: str):
    """Opens TrueNAS's WebSocket API (tests replace this)."""
    from websockets.sync.client import connect as ws_connect

    ctx = None
    if url.startswith("wss://"):
        ctx = ssl.create_default_context()
        if os.environ.get("TRUENAS_VERIFY_TLS", "1") == "0":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
    return ws_connect(url, ssl=ctx, open_timeout=15, close_timeout=5)


def _rpc(method: str, params: list | None = None) -> Any:
    """One JSON-RPC 2.0 call over TrueNAS's WebSocket API, signed in with the API key."""
    base = os.environ.get("TRUENAS_URL", "").rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise TrueNASError("TRUENAS_URL must start with http:// or https://")
    url = "wss://" + base[len("https://") :] if base.startswith("https://") else "ws://" + base[len("http://") :]
    with _open_ws(f"{url}/api/current") as ws:
        calls = [
            ("auth.login_with_api_key", [os.environ.get("TRUENAS_API_KEY", "")]),
            (method, params or []),
        ]
        result = None
        for i, (name, args) in enumerate(calls, start=1):
            ws.send(json.dumps({"jsonrpc": "2.0", "id": i, "method": name, "params": args}))
            reply = json.loads(ws.recv(timeout=30))
            if reply.get("error"):
                raise TrueNASError(f"TrueNAS {name} failed: {reply['error'].get('message') or reply['error']}")
            if name == "auth.login_with_api_key" and reply.get("result") is not True:
                raise TrueNASError("TrueNAS refused the API key")
            result = reply.get("result")
        return result


def _query(path: str, method: str, params: list | None = None, transport=None) -> Any:
    """REST where it exists, JSON-RPC where it doesn't (TrueNAS 27)."""
    try:
        return _get(path, transport)
    except _RestGone:
        logger.debug(f"[TrueNAS] {path} not available over REST; using JSON-RPC {method}")
        return _rpc(method, params)


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
        for p in _query("/pool", "pool.query", transport=transport)
    ]


def datasets(transport=None) -> list[dict[str, Any]]:
    out = []
    for d in _query("/pool/dataset?limit=500", "pool.dataset.query", [[], {"limit": 500}], transport=transport):
        if d.get("type") != "FILESYSTEM":
            continue
        out.append({"id": d.get("id"), "pool": d.get("pool"), "mountpoint": d.get("mountpoint")})
    return out


def shares(transport=None) -> list[dict[str, Any]]:
    out = [
        {"protocol": "smb", "name": s.get("name"), "path": s.get("path"), "enabled": s.get("enabled", True)}
        for s in _query("/sharing/smb", "sharing.smb.query", transport=transport)
    ]
    out += [
        {
            "protocol": "nfs",
            "name": s.get("path") or (s.get("paths") or [""])[0],
            "path": s.get("path") or (s.get("paths") or [""])[0],
            "enabled": s.get("enabled", True),
        }
        for s in _query("/sharing/nfs", "sharing.nfs.query", transport=transport)
    ]
    return out


def create_snapshot(dataset: str, name: str, recursive: bool = True, transport=None) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", name):
        raise TrueNASError("Invalid snapshot name")
    with _client(transport) as c:
        r = c.post("/zfs/snapshot", json={"dataset": dataset, "name": name, "recursive": recursive})
    if r.status_code in REST_GONE:
        # TrueNAS 27: JSON-RPC; the method moved from zfs.snapshot to pool.snapshot in 25.04
        args = [{"dataset": dataset, "name": name, "recursive": recursive}]
        try:
            _rpc("pool.snapshot.create", args)
        except TrueNASError:
            _rpc("zfs.snapshot.create", args)
    elif r.status_code not in (200, 201):
        raise TrueNASError(f"Snapshot failed ({r.status_code}): {r.text[:200]}")
    logger.info(f"[TrueNAS] Snapshot {dataset}@{name} created")
    return {"success": True, "snapshot": f"{dataset}@{name}"}


_SNAP_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,64}")


def _created(snap: dict[str, Any]) -> float | None:
    """When a snapshot was taken, from the properties TrueNAS returns (seconds), if it says."""
    prop = ((snap.get("properties") or {}).get("creation") or {}) if isinstance(snap.get("properties"), dict) else {}
    raw = prop.get("rawvalue") or prop.get("value")
    if not isinstance(raw, (str, int, float)):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def list_snapshots(transport=None) -> list[dict[str, Any]]:
    """Every ZFS snapshot TrueNAS has: [{dataset, name, created}] (FEAT-02)."""
    rows = _query(
        "/zfs/snapshot?limit=5000",
        "pool.snapshot.query",
        [[], {"limit": 5000, "extra": {"properties": ["creation"]}}],
        transport=transport,
    )
    out = []
    for s in rows or []:
        full = str(s.get("name") or s.get("id") or "")
        dataset = s.get("dataset") or full.split("@", 1)[0]
        name = s.get("snapshot_name") or (full.split("@", 1)[1] if "@" in full else "")
        if dataset and name:
            out.append({"dataset": dataset, "name": name, "created": _created(s)})
    return out


def delete_snapshot(dataset: str, name: str, transport=None) -> dict[str, Any]:
    if not _SNAP_NAME.fullmatch(name or "") or not dataset:
        raise TrueNASError("Invalid snapshot name")
    sid = f"{dataset}@{name}"
    from urllib.parse import quote

    with _client(transport) as c:
        r = c.delete(f"/zfs/snapshot/id/{quote(sid, safe='')}")
    if r.status_code in REST_GONE:
        try:
            _rpc("pool.snapshot.delete", [sid])
        except TrueNASError:
            _rpc("zfs.snapshot.delete", [sid])
    elif r.status_code not in (200, 204):
        raise TrueNASError(f"Deleting the snapshot failed ({r.status_code}): {r.text[:200]}")
    logger.info(f"[TrueNAS] Snapshot {sid} deleted")
    return {"success": True, "snapshot": sid}
