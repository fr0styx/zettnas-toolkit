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
    monkeypatch.setattr(disk_safety, "_zfs_members", lambda: {})
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


def test_disk_in_an_imported_zfs_pool_is_never_erased(host, monkeypatch):
    monkeypatch.setattr(disk_safety, "_zfs_members", lambda: {"zza1": "tank"})
    (host / "sys" / "block" / "zza" / "zza1" / "holders").mkdir(parents=True)
    for erase in (False, True):
        r = disk_safety.check_disks(["/dev/zza"], allow_erase=erase)
        assert r and "ZFS pool tank" in r[0]["reason"] and "erasable" not in r[0]


def test_zpool_listing_is_parsed(monkeypatch):
    out = "tank\t3.62T\t1T\t-\n\tmirror-0\t3.62T\n\t/dev/sdb1\t-\t-\n\t/dev/disk/by-id/ata-X-part1\t-\t-\n"
    monkeypatch.setattr(
        disk_safety.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out, returncode=0, stderr="")
    )
    monkeypatch.setattr(disk_safety.os.path, "realpath", lambda p: "/dev/sdc1" if "by-id" in p else p)
    members = disk_safety._zfs_members()
    assert members["sdb1"] == "tank" and members["sdc1"] == "tank"


def test_unreadable_disk_counts_as_not_empty(host, monkeypatch):
    monkeypatch.setattr(disk_safety, "_signature", lambda p: None)
    r = disk_safety.check_disks(["/dev/zza"])
    assert r and "could not check" in r[0]["reason"] and r[0]["erasable"] == "true"


def test_blkid_errors_are_not_read_as_blank(monkeypatch):
    def run(cmd, **kw):
        return SimpleNamespace(stdout="", stderr="permission denied", returncode=4)

    monkeypatch.setattr(disk_safety.subprocess, "run", run)
    assert disk_safety._signature("/dev/zza") is None
    monkeypatch.setattr(
        disk_safety.subprocess, "run", lambda cmd, **kw: SimpleNamespace(stdout="", stderr="", returncode=2)
    )
    assert disk_safety._signature("/dev/zza") == ""


def test_failed_format_is_an_error_not_provisioned(monkeypatch, tmp_path):
    from backend.hardware.pal_storage import GenericLinuxStorageAdapter

    adapter = GenericLinuxStorageAdapter.__new__(GenericLinuxStorageAdapter)
    adapter._pool_path = str(tmp_path)
    monkeypatch.setattr(adapter, "_resolve_disk_path", lambda d: d, raising=False)
    monkeypatch.setattr(adapter, "_run_cmd", lambda cmd: (1, "", "Device /dev/zza is busy"), raising=False)
    with pytest.raises(RuntimeError, match="mkfs.xfs failed.*busy"):
        adapter.create_pool(
            name="p1", fs_type="xfs", profile="single", disks=["/dev/zza"], mountpoint=str(tmp_path / "p1")
        )
