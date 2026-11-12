"""S29 (owner, 12 Nov 2026: A + B): delete a pool and erase its drives, only drives its own tool lists
and whose on-disk label carries the pool's id. A: real Btrfs pools on image files, no drive touched."""

import os
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.hardware.pal import pool_erase as pe


def pool(**kw):
    base = {"id": "tank", "name": "tank", "fs_type": "zfs", "pool_type": "zfs_pool", "mountpoint": "/mnt/tank"}
    return SimpleNamespace(**(base | kw))


def runner(answers):
    calls = []

    def run(cmd):
        calls.append(cmd)
        for prefix, ans in answers:
            if cmd[: len(prefix)] == prefix:
                return ans
        return (0, "", "")

    run.calls = calls
    return run


def test_kinds():
    assert pe.kind_of(pool()) == "zfs"
    assert pe.kind_of(pool(fs_type="btrfs", pool_type="btrfs_raid")) == "btrfs"
    assert pe.kind_of(pool(id="md0", fs_type="xfs", pool_type="mdadm")) == "md"
    assert pe.kind_of(pool(id="unraid_array", fs_type="unraid", pool_type="unraid_array")) == ""


def test_zfs_plan_and_erase():
    run = runner(
        [
            (["zpool", "get"], (0, "123456\n", "")),
            (
                ["zpool", "status"],
                (
                    0,
                    "  pool: tank\n config:\n\ttank\n\t  mirror-0\n\t    /dev/sdb1  ONLINE\n\t    /dev/sdc1  ONLINE\n",
                    "",
                ),
            ),
            (["zdb", "-l", "/dev/sdb1"], (0, "    pool_guid: 123456\n", "")),
            (["zdb", "-l", "/dev/sdc1"], (0, "    pool_guid: 123456\n", "")),
        ]
    )
    p = pe.plan(pool(), run)
    assert p["drives"] == ["/dev/sdb1", "/dev/sdc1"] and p["kind"] == "zfs"
    assert pe.execute(p, run) == ["/dev/sdb1", "/dev/sdc1"]
    assert ["zpool", "destroy", "-f", "tank"] in run.calls
    assert ["zpool", "labelclear", "-f", "/dev/sdb1"] in run.calls and ["wipefs", "-a", "/dev/sdc1"] in run.calls


def test_one_unconfirmed_drive_refuses_everything():
    run = runner(
        [
            (["zpool", "get"], (0, "123456\n", "")),
            (["zpool", "status"], (0, "\t    /dev/sdb1  ONLINE\n\t    /dev/sdd1  ONLINE\n", "")),
            (["zdb", "-l", "/dev/sdb1"], (0, "    pool_guid: 123456\n", "")),
            (["zdb", "-l", "/dev/sdd1"], (0, "    pool_guid: 999\n", "")),
        ]
    )
    with pytest.raises(pe.EraseRefused, match="/dev/sdd1"):
        pe.plan(pool(), run)
    assert not any(
        c[0] in ("wipefs", "zpool") and c[1] in ("destroy", "labelclear", "-a") for c in run.calls if len(c) > 1
    )


def test_md_plan():
    run = runner(
        [
            (
                ["mdadm", "--detail"],
                (0, "MD_UUID=aa:bb\nMD_DEVICE_dev_sdb_DEV=/dev/sdb\nMD_DEVICE_dev_sdc_DEV=/dev/sdc\n", ""),
            ),
            (["mdadm", "--examine"], (0, "MD_UUID=aa:bb\n", "")),
        ]
    )
    p = pe.plan(pool(id="md0", fs_type="xfs", pool_type="mdadm", mountpoint="/mnt/md0"), run)
    assert p["drives"] == ["/dev/sdb", "/dev/sdc"]
    assert pe.execute(p, run) == ["/dev/sdb", "/dev/sdc"]
    assert ["umount", "/mnt/md0"] in run.calls and ["mdadm", "--stop", "/dev/md0"] in run.calls
    assert ["mdadm", "--zero-superblock", "/dev/sdb"] in run.calls


@pytest.mark.parametrize(
    "p, answers",
    [
        (pool(id="unraid_array", fs_type="unraid", pool_type="unraid_array"), []),
        (pool(), [(["zpool", "get"], (1, "", "no such pool"))]),
        (pool(fs_type="btrfs", pool_type="btrfs_raid"), [(["btrfs", "filesystem"], (1, "", "nope"))]),
        (pool(id="md0", fs_type="xfs", pool_type="mdadm"), [(["mdadm", "--detail"], (1, "", "nope"))]),
        (pool(), [(["zpool", "get"], (0, "1\n", "")), (["zpool", "status"], (0, "nothing", ""))]),
    ],
)
def test_refusals_change_nothing(p, answers):
    run = runner(answers)
    with pytest.raises(pe.EraseRefused):
        pe.plan(p, run)
    assert not any(c[0] == "wipefs" for c in run.calls)


def test_a_drive_in_use_or_a_failed_wipe_stops():
    busy = runner([(["umount"], (32, "", "target is busy"))])
    with pytest.raises(pe.EraseRefused, match="in use"):
        pe.execute(
            {"kind": "btrfs", "pool": "data", "name": "data", "drives": ["/dev/sdb"], "mountpoint": "/mnt/data"}, busy
        )
    failed = runner([(["wipefs"], (1, "", "permission denied"))])
    with pytest.raises(pe.EraseRefused, match="was not erased"):
        pe.execute({"kind": "btrfs", "pool": "data", "name": "data", "drives": ["/dev/sdb"], "mountpoint": ""}, failed)
    zfs_no = runner([(["zpool", "destroy"], (1, "", "busy"))])
    with pytest.raises(pe.EraseRefused, match="did not delete"):
        pe.execute({"kind": "zfs", "pool": "tank", "name": "tank", "drives": ["/dev/sdb1"]}, zfs_no)


def test_label_reader_for_an_unknown_kind_is_empty():
    assert pe.label_of("/dev/sdb", "xfs", runner([])) == ""


# ---- A: pretend drives. Real Btrfs on image files: no device, real or loop, is touched.

needs_btrfs = pytest.mark.skipif(
    not (shutil.which("mkfs.btrfs") and shutil.which("wipefs") and shutil.which("blkid")),
    reason="btrfs-progs, wipefs and blkid needed",
)


def real(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def make_image(path, size_mb=128):
    with open(path, "wb") as fh:
        fh.truncate(size_mb * 1024 * 1024)
    return str(path)


@needs_btrfs
def test_pretend_drives_erase_only_the_pool(tmp_path):
    a, b = make_image(tmp_path / "a.img"), make_image(tmp_path / "b.img")
    other = make_image(tmp_path / "other.img")
    assert real(["mkfs.btrfs", "-q", "-f", "-d", "raid1", "-m", "raid1", a, b])[0] == 0
    assert real(["mkfs.btrfs", "-q", "-f", other])[0] == 0
    fsid = pe.label_of(a, "btrfs", real)
    assert fsid and pe.label_of(b, "btrfs", real) == fsid and pe.label_of(other, "btrfs", real) not in ("", fsid)
    p = pool(id="data", name="data", fs_type="btrfs", pool_type="btrfs_raid", mountpoint="")

    # the tool's listing (a mounted pool's `btrfs filesystem show`) is the only part simulated
    with patch.object(pe, "pool_id_and_devices", return_value=(fsid, [a, b, other])):
        with pytest.raises(pe.EraseRefused, match="other.img"):
            pe.plan(p, real)  # the outsider refuses everything
    assert pe.label_of(a, "btrfs", real) == fsid  # nothing was erased

    with patch.object(pe, "pool_id_and_devices", return_value=(fsid, [a, b])):
        plan = pe.plan(p, real)
        assert plan["drives"] == [a, b]
        assert pe.execute(plan, real) == [a, b]
    assert pe.label_of(a, "btrfs", real) == "" and pe.label_of(b, "btrfs", real) == ""
    assert pe.label_of(other, "btrfs", real) not in ("", fsid)  # the drive outside the pool kept its filesystem
    assert os.path.getsize(other) == 128 * 1024 * 1024
