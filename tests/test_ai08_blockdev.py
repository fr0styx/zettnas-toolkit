"""AI-08: the standby guard finds the real disks under a path on any storage stack."""

import os
from types import SimpleNamespace

from backend.hardware import blockdev


def _sys(tmp_path, disks):
    """Builds a fake /sys: disks = {name: {"rot": "1", "parts": [...], "slaves": [...]}}."""
    sysroot = tmp_path / "sys"
    devices = sysroot / "devices"
    for name, spec in disks.items():
        d = devices / name
        (d / "queue").mkdir(parents=True)
        (d / "queue" / "rotational").write_text(spec.get("rot", "1"))
        if spec.get("slaves"):
            (d / "slaves").mkdir()
            for s in spec["slaves"]:
                (d / "slaves" / s).touch()
        for p in spec.get("parts", []):
            (d / p).mkdir()
            (d / p / "partition").write_text("1")
        majmin = spec.get("majmin")
        for target, nm in [(d, name)] + [(d / p, p) for p in spec.get("parts", [])]:
            (sysroot / "class" / "block").mkdir(parents=True, exist_ok=True)
            os.symlink(target, sysroot / "class" / "block" / nm)
        (sysroot / "block").mkdir(exist_ok=True)
        os.symlink(d, sysroot / "block" / name)
        if majmin:
            (sysroot / "dev" / "block").mkdir(parents=True, exist_ok=True)
            target = d / spec["majmin_part"] if spec.get("majmin_part") else d
            os.symlink(target, sysroot / "dev" / "block" / majmin)
    return str(sysroot)


def mnt(mountpoint, fstype, source, majmin="0:0"):
    return {"mountpoint": mountpoint, "fstype": fstype, "source": source, "majmin": majmin, "root": "/"}


def test_plain_partition(tmp_path):
    sysroot = _sys(tmp_path, {"sdb": {"parts": ["sdb1"], "majmin": "8:17", "majmin_part": "sdb1"}})
    mounts = [mnt("/", "overlay", "overlay"), mnt("/data", "ext4", "/dev/sdb1", "8:17")]
    assert blockdev.disks_for_path("/data/photos/a.jpg", mounts, sysroot) == ["sdb"]


def test_mdadm_and_ssd_filtering(tmp_path):
    sysroot = _sys(
        tmp_path,
        {
            "md0": {"slaves": ["sdc1", "sdd1"], "majmin": "9:0"},
            "sdc": {"parts": ["sdc1"]},
            "sdd": {"parts": ["sdd1"]},
            "nvme0n1": {"rot": "0", "majmin": "259:0"},
        },
    )
    mounts = [mnt("/srv", "xfs", "/dev/md0", "9:0"), mnt("/fast", "ext4", "/dev/nvme0n1", "259:0")]
    assert blockdev.disks_for_path("/srv/x", mounts, sysroot) == ["sdc", "sdd"]
    assert blockdev.disks_for_path("/fast/x", mounts, sysroot) == []  # SSDs don't spin down


def test_zfs_pool(tmp_path):
    sysroot = _sys(tmp_path, {"sde": {"parts": ["sde1"]}, "sdf": {"parts": ["sdf1"]}})
    out = """  pool: tank\n config:\n\n  NAME STATE\n  tank ONLINE\n   mirror-0 ONLINE\n    /dev/sde1 ONLINE\n    /dev/sdf1 ONLINE\n"""
    runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=out)  # noqa: E731
    blockdev._ZPOOL_CACHE.clear()
    mounts = [mnt("/tank", "zfs", "tank/media")]
    assert blockdev.disks_for_path("/tank/media/film.mkv", mounts, sysroot, runner) == ["sde", "sdf"]


def test_btrfs_multi_device(tmp_path):
    sysroot = _sys(tmp_path, {"sdg": {"parts": ["sdg1"]}, "sdh": {"parts": ["sdh1"]}})
    devdir = tmp_path / "sys" / "fs" / "btrfs" / "uuid-1" / "devices"
    devdir.mkdir(parents=True)
    (devdir / "sdg1").touch()
    (devdir / "sdh1").touch()
    mounts = [mnt("/pool", "btrfs", "/dev/sdg1", "0:45")]
    assert blockdev.disks_for_path("/pool/x", mounts, sysroot) == ["sdg", "sdh"]


def test_network_and_unknown(tmp_path):
    sysroot = _sys(tmp_path, {})
    mounts = [
        mnt("/mnt/remotes/gdrive", "fuse.rclone", "gdrive:"),
        mnt("/nas", "nfs4", "nas:/x"),
        mnt("/weird", "ext4", "/dev/mapper/gone", "253:9"),
        mnt("/share", "fuse.shfs", "shfs"),
    ]
    assert blockdev.disks_for_path("/mnt/remotes/gdrive/a", mounts, sysroot) == []
    assert blockdev.disks_for_path("/nas/a", mounts, sysroot) == []
    assert blockdev.disks_for_path("/weird/a", mounts, sysroot) is None  # fail closed
    assert blockdev.disks_for_path("/share/a", mounts, sysroot) is None


def test_guard_fails_closed_and_checks_every_disk(monkeypatch):
    from backend.services import rag_engine

    monkeypatch.setattr("backend.services.rag_standby._get_unraid_disks_and_shares", lambda: ({}, {}))
    monkeypatch.setattr(
        blockdev, "disks_for_path", lambda p, *a, **k: {"/srv/a": ["sdc", "sdd"], "/weird/a": None, "/nas/a": []}[p]
    )
    assert rag_engine.resolve_path_backing_dev("/srv/a") == "sdc,sdd"
    assert rag_engine.resolve_path_backing_dev("/weird/a") == rag_engine.UNKNOWN_BACKING_DEV
    assert rag_engine.resolve_path_backing_dev("/nas/a") == ""
    asleep = {"sdd"}
    monkeypatch.setattr("backend.services.rag_standby._disk_reports_standby", lambda d: d in asleep)
    assert rag_engine.is_backing_disk_in_standby("sdc,sdd") is True
    asleep.clear()
    assert rag_engine.is_backing_disk_in_standby("sdc,sdd") is False
    assert rag_engine.is_backing_disk_in_standby(rag_engine.UNKNOWN_BACKING_DEV) is True
    monkeypatch.setenv("ZETTNAS_STANDBY_UNKNOWN", "allow")
    assert rag_engine.is_backing_disk_in_standby(rag_engine.UNKNOWN_BACKING_DEV) is False
