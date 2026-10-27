"""B12a (FEAT-02, D2): on TrueNAS, share snapshots go through its API: taken on the share's
dataset, listed with the path ZFS shows them at, and deleted again for retention."""

import json

import httpx
import pytest

from backend.hardware.pal.truenas import TrueNASStorageAdapter
from backend.services import truenas_api

DATASETS = [
    {"id": "tank", "type": "FILESYSTEM", "pool": "tank", "mountpoint": "/mnt/tank"},
    {"id": "tank/family", "type": "FILESYSTEM", "pool": "tank", "mountpoint": "/mnt/tank/family"},
]
SNAPS = [
    {
        "name": "tank/family@auto-20261027-1000",
        "dataset": "tank/family",
        "snapshot_name": "auto-20261027-1000",
        "properties": {"creation": {"rawvalue": "1793095200"}},
    },
    {"name": "tank@manual", "dataset": "tank"},
]


@pytest.fixture
def truenas(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "https://truenas.test")
    monkeypatch.setenv("TRUENAS_API_KEY", "1-abc")
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.raw_path.decode().split("?")[0], req.content))
        if req.url.path == "/api/v2.0/pool/dataset":
            return httpx.Response(200, json=DATASETS)
        if req.url.path == "/api/v2.0/zfs/snapshot" and req.method == "GET":
            return httpx.Response(200, json=SNAPS)
        if req.url.path == "/api/v2.0/zfs/snapshot" and req.method == "POST":
            return httpx.Response(200, json={})
        if req.url.path.startswith("/api/v2.0/zfs/snapshot/id/") and req.method == "DELETE":
            return httpx.Response(200, json=True)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = truenas_api._client
    monkeypatch.setattr(truenas_api, "_client", lambda t=None: real_client(transport))
    return seen


def test_the_api_lists_and_deletes_snapshots(truenas):
    snaps = truenas_api.list_snapshots()
    assert snaps[0] == {"dataset": "tank/family", "name": "auto-20261027-1000", "created": 1793095200.0}
    assert snaps[1]["name"] == "manual" and snaps[1]["created"] is None
    assert truenas_api.delete_snapshot("tank/family", "auto-20261027-1000")["success"]
    method, path, _ = truenas[-1]
    assert method == "DELETE" and path == "/api/v2.0/zfs/snapshot/id/tank%2Ffamily%40auto-20261027-1000"
    with pytest.raises(truenas_api.TrueNASError):
        truenas_api.delete_snapshot("tank/family", "bad;name")


def test_a_share_snapshot_is_taken_on_its_dataset(truenas):
    adapter = TrueNASStorageAdapter.__new__(TrueNASStorageAdapter)
    res = adapter.create_snapshot("tank", "family", "family@auto-20261027-1100", readonly=True)
    assert res["snapshot"] == "tank/family@auto-20261027-1100"
    posted = json.loads(truenas[-1][2])
    assert posted == {"dataset": "tank/family", "name": "auto-20261027-1100", "recursive": True}


def test_snapshots_are_listed_by_share_with_their_zfs_path(truenas):
    adapter = TrueNASStorageAdapter.__new__(TrueNASStorageAdapter)
    by_name = {s["name"]: s for s in adapter.list_snapshots("tank")}
    fam = by_name["family@auto-20261027-1000"]
    assert fam["path"] == "/mnt/tank/family/.zfs/snapshot/auto-20261027-1000" and fam["created_at"] == 1793095200.0
    assert "tank@manual" in by_name


def test_retention_deletes_through_the_api(truenas):
    adapter = TrueNASStorageAdapter.__new__(TrueNASStorageAdapter)
    adapter.delete_snapshot("tank", "family@auto-20261027-1000")
    assert truenas[-1][0] == "DELETE"


def test_without_the_api_truenas_takes_no_snapshots(monkeypatch):
    monkeypatch.delenv("TRUENAS_URL", raising=False)
    adapter = TrueNASStorageAdapter.__new__(TrueNASStorageAdapter)
    assert adapter.get_capabilities().can_snapshot is False
    assert adapter.list_snapshots("tank") == []


def test_the_old_json_rpc_name_is_tried_when_rest_is_gone(monkeypatch):
    monkeypatch.setenv("TRUENAS_URL", "https://truenas.test")
    monkeypatch.setenv("TRUENAS_API_KEY", "1-abc")
    gone = httpx.MockTransport(lambda req: httpx.Response(404))
    real_client = truenas_api._client
    monkeypatch.setattr(truenas_api, "_client", lambda t=None: real_client(gone))
    calls = []

    def fake_rpc(method, params=None):
        calls.append(method)
        if method == "pool.snapshot.delete":
            raise truenas_api.TrueNASError("no such method")
        return True

    monkeypatch.setattr(truenas_api, "_rpc", fake_rpc)
    truenas_api.delete_snapshot("tank/family", "auto-1")
    assert calls == ["pool.snapshot.delete", "zfs.snapshot.delete"]
