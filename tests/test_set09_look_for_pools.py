"""SET-09: looking for pools on other drives reads the label of every drive. It ran at each
opening and each Refresh of the Pools tab; in a container install it can find nothing."""

from backend.api import storage as storage_api


class Adapter:
    def __init__(self):
        self.looked = 0

    def discover_external_pools(self):
        self.looked += 1
        return [{"pool_id": "backup", "fs_type": "zfs"}]


def test_a_container_install_is_not_scanned_and_the_page_is_told(client, auth_headers, monkeypatch):
    adapter = Adapter()
    monkeypatch.setattr(storage_api, "get_storage_platform", lambda: adapter)
    monkeypatch.setattr(storage_api, "_in_container", lambda: True)
    r = client.get("/api/storage/pools/discover", headers=auth_headers).json()
    assert r["discovered_pools"] == [] and r["available"] is False
    assert adapter.looked == 0

    monkeypatch.setattr(storage_api, "_in_container", lambda: False)
    r = client.get("/api/storage/pools/discover", headers=auth_headers).json()
    assert r["available"] is True and [p["pool_id"] for p in r["discovered_pools"]] == ["backup"]
    assert adapter.looked == 1


def test_the_platform_answer_says_whether_the_look_is_offered(client, auth_headers, monkeypatch):
    monkeypatch.setattr(storage_api, "_in_container", lambda: True)
    assert client.get("/api/storage/platform", headers=auth_headers).json()["can_look_for_pools"] is False
