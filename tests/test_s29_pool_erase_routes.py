"""S29 routes: offered only where Kiboto manages the host and the pool names its drives (B)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.hardware.pal.base import PlatformCapabilityError


def caps(observer=False, destroy=True):
    return SimpleNamespace(
        is_observer_mode=observer, can_destroy_pools=destroy, can_trigger_scrub=True, can_export_pools=True
    )


def adapter(observer=False, destroy=True, pools=()):
    a = MagicMock()
    a.get_capabilities.return_value = caps(observer, destroy)
    a.get_platform_type.return_value = SimpleNamespace(value="generic_linux")
    a.is_storage_busy.return_value = False
    a.list_pools.return_value = list(pools)
    return a


def pool_obj(**kw):
    p = MagicMock()
    data = {"id": "tank", "name": "tank", "fs_type": "zfs", "pool_type": "zfs_pool"} | kw
    for k, v in data.items():
        setattr(p, k, v)
    p.model_dump.return_value = dict(data)
    return p


def test_the_flag_follows_the_host_and_the_kind(client, auth_headers):
    a = adapter(pools=[pool_obj(), pool_obj(id="disk1", fs_type="xfs", pool_type="single")])
    with patch("backend.api.storage.get_storage_platform", return_value=a):
        rows = client.get("/api/storage/pools", headers=auth_headers).json()["pools"]
    assert [r["erasable"] for r in rows] == [True, False]
    a = adapter(observer=True, destroy=False, pools=[pool_obj()])
    with patch("backend.api.storage.get_storage_platform", return_value=a):
        assert client.get("/api/storage/pools", headers=auth_headers).json()["pools"][0]["erasable"] is False


def test_the_plan_lists_drives_and_shares(client, auth_headers):
    a = adapter()
    a.erase_plan.return_value = {"pool": "tank", "drives": ["/dev/sdb1"], "mountpoint": "/mnt/tank"}
    a.list_shares.return_value = [
        SimpleNamespace(name="photos", mountpoint="/mnt/tank/photos"),
        SimpleNamespace(name="other", mountpoint="/mnt/user/other"),
    ]
    with patch("backend.api.storage.get_storage_platform", return_value=a):
        r = client.get("/api/storage/pools/tank/erase-plan", headers=auth_headers)
    assert r.status_code == 200 and r.json()["shares"] == ["photos"] and r.json()["drives"] == ["/dev/sdb1"]


def test_the_plan_refusals(client, auth_headers):
    for exc, code in (
        (PlatformCapabilityError("in Unraid"), 403),
        (LookupError("no pool"), 404),
        (RuntimeError("not certain"), 409),
    ):
        a = adapter()
        a.erase_plan.side_effect = exc
        with patch("backend.api.storage.get_storage_platform", return_value=a):
            assert client.get("/api/storage/pools/tank/erase-plan", headers=auth_headers).status_code == code


@pytest.mark.real_confirmations
def test_erase_needs_the_name_the_password_and_a_confirmation(client, auth_headers, monkeypatch):
    a = adapter()
    a.erase_pool.return_value = {"status": "erased", "pool_id": "tank", "drives": ["/dev/sdb1"]}
    monkeypatch.setattr("backend.passwords.verify_password", lambda pw, h: pw == "right")
    monkeypatch.setattr("backend.users_db.get_user_by_username", lambda u: {"password_hash": "x"})
    with patch("backend.api.storage.get_storage_platform", return_value=a):
        assert (
            client.post(
                "/api/storage/pools/tank/erase",
                json={"confirm_name": "tank", "current_password": "right"},
                headers=auth_headers,
            ).status_code
            == 428
        )
        hdr = auth_headers | {"x-confirm-token": _token(client, auth_headers, "tank")}
        assert (
            client.post(
                "/api/storage/pools/tank/erase", json={"confirm_name": "tan", "current_password": "right"}, headers=hdr
            ).status_code
            == 400
        )
        hdr = auth_headers | {"x-confirm-token": _token(client, auth_headers, "tank")}
        assert (
            client.post(
                "/api/storage/pools/tank/erase", json={"confirm_name": "tank", "current_password": "wrong"}, headers=hdr
            ).status_code
            == 403
        )
        hdr = auth_headers | {"x-confirm-token": _token(client, auth_headers, "tank")}
        r = client.post(
            "/api/storage/pools/tank/erase", json={"confirm_name": "tank", "current_password": "right"}, headers=hdr
        )
    assert r.status_code == 200 and r.json()["drives"] == ["/dev/sdb1"]
    for exc, code in (
        (PlatformCapabilityError("in Unraid"), 403),
        (LookupError("x"), 404),
        (RuntimeError("not certain"), 409),
    ):
        a.erase_pool.side_effect = exc
        with patch("backend.api.storage.get_storage_platform", return_value=a):
            hdr = auth_headers | {"x-confirm-token": _token(client, auth_headers, "tank")}
            assert (
                client.post(
                    "/api/storage/pools/tank/erase",
                    json={"confirm_name": "tank", "current_password": "right"},
                    headers=hdr,
                ).status_code
                == code
            )


def _token(client, auth_headers, target):
    r = client.post("/api/confirmations", json={"action": "storage.pool.erase", "target": target}, headers=auth_headers)
    return r.json().get("token") or r.json().get("confirm_token")


def test_hosts_kiboto_does_not_manage_refuse_both():
    import pytest

    from backend.hardware.pal.unraid import UnraidStorageAdapter

    a = UnraidStorageAdapter.__new__(UnraidStorageAdapter)
    with pytest.raises(PlatformCapabilityError):
        a.erase_plan("cache")
    with pytest.raises(PlatformCapabilityError):
        a.erase_pool("cache")


def test_generic_linux_turns_refusals_into_errors(monkeypatch):
    from backend.hardware.pal import pool_erase
    from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter

    a = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    monkeypatch.setattr(
        a,
        "resolve_pool",
        lambda pid: SimpleNamespace(id=pid, name=pid, fs_type="xfs", pool_type="single", mountpoint=""),
        raising=False,
    )
    with pytest.raises(RuntimeError):
        a.erase_plan("disk1")
    with pytest.raises(RuntimeError):
        a.erase_pool("disk1")
    monkeypatch.setattr(
        pool_erase, "plan", lambda p, run: {"pool": "tank", "drives": ["/dev/sdb1"], "kind": "zfs", "name": "tank"}
    )
    monkeypatch.setattr(pool_erase, "execute", lambda p, run: ["/dev/sdb1"])
    assert a.erase_pool("tank") == {"status": "erased", "pool_id": "tank", "drives": ["/dev/sdb1"]}
    assert a.erase_plan("tank")["drives"] == ["/dev/sdb1"]
