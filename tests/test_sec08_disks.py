"""SEC-08: disks are checked before a pool formats them."""

from types import SimpleNamespace

import pytest

from backend.api import storage as storage_api
from backend.hardware import disk_safety


@pytest.fixture
def host(tmp_path, monkeypatch):
    sys_dir, proc_dir = tmp_path / "sys", tmp_path / "proc"
    for disk in ("zza", "zzb", "zzc", "zzd"):
        (sys_dir / "block" / disk / "holders").mkdir(parents=True)
    (sys_dir / "block" / "zzb" / "zzb1" / "holders").mkdir(parents=True)
    (sys_dir / "block" / "zzc" / "holders" / "md0").mkdir(parents=True)
    (sys_dir / "block" / "zzd" / "zzd1" / "holders").mkdir(parents=True)
    (proc_dir / "1").mkdir(parents=True)
    (proc_dir / "1" / "mounts").write_text("/dev/zzb1 /mnt/data ext4 rw 0 0\n")
    (proc_dir / "swaps").write_text("Filename Type Size Used Priority\n")
    monkeypatch.setattr(disk_safety, "HOST_SYS", str(sys_dir))
    monkeypatch.setattr(disk_safety, "HOST_PROC", str(proc_dir))
    monkeypatch.setattr(disk_safety, "_is_block", lambda p: p.startswith("/dev/zz"))
    monkeypatch.setattr(disk_safety, "_signature", lambda p: "")
    return tmp_path


def _reasons(disks, **kw):
    return {p["disk"]: p["reason"] for p in disk_safety.check_disks(disks, **kw)}


def test_blank_disk_is_clear(host):
    assert disk_safety.check_disks(["/dev/zza"]) == []


def test_mounted_partition_holder_and_non_device_are_refused(host):
    r = _reasons(["/dev/zzb", "/dev/zzc", "/etc/passwd", "/dev/zzb1"])
    assert "mounted at /mnt/data" in r["/dev/zzb"]
    assert "md0" in r["/dev/zzc"]
    assert "block device" in r["/etc/passwd"]
    assert "whole disk" in r["/dev/zzb1"]


def test_existing_data_needs_explicit_erase(host, monkeypatch):
    r = disk_safety.check_disks(["/dev/zzd"])
    assert r and r[0]["erasable"] == "true" and "partition" in r[0]["reason"]
    assert disk_safety.check_disks(["/dev/zzd"], allow_erase=True) == []
    monkeypatch.setattr(disk_safety, "_signature", lambda p: "zfs_member")
    assert "zfs_member" in _reasons(["/dev/zza"])["/dev/zza"]
    # erase never overrides "mounted" or "in RAID"
    assert _reasons(["/dev/zzb"], allow_erase=True)


def test_pool_api_requires_typed_name_password_and_safe_disks(client, auth_headers, host, monkeypatch):
    created = []
    fake = SimpleNamespace(
        get_capabilities=lambda: SimpleNamespace(is_observer_mode=False),
        get_platform_type=lambda: SimpleNamespace(value="generic"),
        create_pool=lambda **kw: created.append(kw) or {"status": "provisioned"},
    )
    monkeypatch.setattr(storage_api, "get_storage_platform", lambda: fake)
    body = {"name": "tank", "fs_type": "btrfs", "profile": "single", "disks": ["/dev/zzb"]}

    assert client.post("/api/storage/pools", json=body, headers=auth_headers).status_code == 400  # no typed name
    body["confirm_name"] = "tank"
    body["current_password"] = "wrong"
    assert client.post("/api/storage/pools", json=body, headers=auth_headers).status_code == 403
    body["current_password"] = "admin"
    res = client.post("/api/storage/pools", json=body, headers=auth_headers)
    assert res.status_code == 409 and res.json()["error"] == "disks_not_safe" and not created
    body["mountpoint"] = "/etc/evil"
    body["disks"] = ["/dev/zza"]
    assert client.post("/api/storage/pools", json=body, headers=auth_headers).status_code == 400
    body.pop("mountpoint")
    res = client.post("/api/storage/pools", json=body, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert created and created[0]["disks"] == ["/dev/zza"]
