"""Btrfs volumes count as protected only when their data profile keeps copies on other
disks; FygoOS volumes used to be reported as parity-protected for any Btrfs."""

import os
from collections import namedtuple

import pytest

from backend.hardware import pal_storage
from backend.hardware.pal_storage import FygoOSStorageAdapter, btrfs_data_profiles, btrfs_is_redundant


def _fs(sys_root, fsid, devices, profiles):
    base = os.path.join(sys_root, "fs", "btrfs", fsid)
    os.makedirs(os.path.join(base, "devices"), exist_ok=True)
    for d in devices:
        open(os.path.join(base, "devices", d), "w").close()
    for p in profiles:
        os.makedirs(os.path.join(base, "allocation", "data", p), exist_ok=True)


def test_profiles_from_sysfs(tmp_path):
    sys_root = str(tmp_path)
    _fs(sys_root, "aaaa", ["sdb", "sdc"], ["raid1"])
    _fs(sys_root, "bbbb", ["sdd"], ["single"])
    _fs(sys_root, "cccc", ["nvme0n1p2"], ["dup"])
    assert btrfs_data_profiles("/dev/sdc", (sys_root,)) == ["raid1"]
    assert btrfs_data_profiles("/dev/sdd", (sys_root,)) == ["single"]
    assert btrfs_data_profiles("/dev/nvme0n1p2", (sys_root,)) == ["dup"]
    assert btrfs_data_profiles("/dev/sdz", (sys_root,)) == []
    assert btrfs_data_profiles("", (sys_root,)) == []
    assert btrfs_data_profiles("/dev/sdb", (str(tmp_path / "nothing"),)) == []


@pytest.mark.parametrize(
    ("profiles", "safe"),
    [
        (["raid1"], True),
        (["raid10"], True),
        (["raid1c3"], True),
        (["raid6"], True),
        (["single"], False),
        (["dup"], False),
        (["raid0"], False),
        (["raid1", "single"], False),
        ([], False),
    ],
)
def test_what_counts_as_protected(profiles, safe):
    assert btrfs_is_redundant(profiles) is safe


Usage = namedtuple("Usage", "total used free")


@pytest.fixture
def fygo(monkeypatch):
    a = FygoOSStorageAdapter(pool_path="/media")
    monkeypatch.setattr(a, "_discover_hal_disks", lambda: [])
    monkeypatch.setattr(pal_storage.shutil, "disk_usage", lambda p: Usage(1000, 250, 750))
    return a


def test_fygoos_reports_protection_from_the_profile(fygo, monkeypatch):
    monkeypatch.setattr(
        fygo,
        "_parse_mounts",
        lambda: [
            {"device": "/dev/sdb", "mountpoint": "/media/mirror", "fstype": "btrfs"},
            {"device": "/dev/sdd", "mountpoint": "/media/single", "fstype": "btrfs"},
            {"device": "/dev/sde1", "mountpoint": "/media/usb", "fstype": "ext4"},
            {"device": "/dev/sdf1", "mountpoint": "/srv/elsewhere", "fstype": "ext4"},
        ],
    )
    monkeypatch.setattr(
        pal_storage, "btrfs_data_profiles", lambda dev, *a: {"/dev/sdb": ["raid1"], "/dev/sdd": ["single"]}.get(dev, [])
    )
    pools = {p.id: p for p in fygo.list_pools()}
    assert set(pools) == {"mirror", "single", "usb"}
    assert (
        pools["mirror"].parity_protected is True
        and pools["mirror"].pool_type == "btrfs_raid"
        and pools["mirror"].fs_profile == "raid1"
    )
    assert pools["single"].parity_protected is False and pools["single"].pool_type == "single"
    assert pools["usb"].parity_protected is False and pools["usb"].used_pct == 25.0


def test_fygoos_falls_back_to_the_pool_folder(fygo, monkeypatch):
    monkeypatch.setattr(fygo, "_parse_mounts", lambda: [])
    pools = fygo.list_pools()
    assert [p.id for p in pools] == ["fygoos_main"] and pools[0].total_bytes == 1000

    def unreadable(path):
        raise OSError("gone")

    monkeypatch.setattr(pal_storage.shutil, "disk_usage", unreadable)
    assert fygo.list_pools()[0].total_bytes == 0
    assert fygo.trigger_scrub("x")["status"] == "monitoring" and fygo.is_storage_busy() is False


# ---------------------------------------------------------------------------
# mdadm scrub on ZettOS: cancelling never stops a rebuild
# ---------------------------------------------------------------------------


@pytest.fixture
def zettos_md(tmp_path, monkeypatch):
    from backend.hardware.pal_storage import ZettOSStorageAdapter

    a = ZettOSStorageAdapter(pool_path="/mnt/user")
    sa = tmp_path / "block" / "md0" / "md"
    sa.mkdir(parents=True)
    (sa / "sync_action").write_text("idle\n")
    monkeypatch.setattr(pal_storage, "HOST_SYS", str(tmp_path))
    state = {"sync_action": None}
    monkeypatch.setattr(
        a, "_parse_mdstat", lambda: {"md0": {"sync_action": state["sync_action"], "progress_pct": 42.0}}
    )
    return a, sa / "sync_action", state


def test_md_scrub_start_and_cancel(zettos_md):
    a, sa, state = zettos_md
    assert a.trigger_scrub("md0", "start")["status"] == "started" and sa.read_text() == "check\n"
    state["sync_action"] = "check"
    assert a.trigger_scrub("/dev/md0", "cancel")["status"] == "cancelled" and sa.read_text() == "idle\n"


@pytest.mark.parametrize("running", ["recover", "resync", "reshape"])
def test_md_cancel_leaves_a_rebuild_running(zettos_md, running):
    a, sa, state = zettos_md
    sa.write_text(running + "\n")
    state["sync_action"] = running
    res = a.trigger_scrub("md0", "cancel")
    assert res["status"] == "active" and res["sync_action"] == running
    assert sa.read_text() == running + "\n"  # untouched


def test_zfs_scrub_commands(monkeypatch):
    from backend.hardware.pal_storage import ZettOSStorageAdapter

    a = ZettOSStorageAdapter(pool_path="/mnt/user")
    ran = []
    monkeypatch.setattr(a, "_run_cmd", lambda cmd: ran.append(cmd) or (0, "  scan: scrub in progress since Sat", ""))
    assert a.trigger_scrub("tank", "start")["status"] == "started"
    assert a.trigger_scrub("tank", "cancel")["status"] == "cancelled"
    assert a.trigger_scrub("tank", "status")["status"] == "active"
    assert ran == [["zpool", "scrub", "tank"], ["zpool", "scrub", "-s", "tank"], ["zpool", "status", "tank"]]


@pytest.mark.parametrize("pool_id", ["-s", "tank -s", "a;b", ""])
def test_scrub_route_refuses_odd_pool_names(client, auth_headers, pool_id):
    r = client.post("/api/storage/scrub", json={"pool_id": pool_id, "action": "start"}, headers=auth_headers)
    assert r.status_code == 422
