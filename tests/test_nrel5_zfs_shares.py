"""NREL-5: on a ZFS pool a new share is a dataset of its own, and its snapshots are ZFS snapshots
under the names ZettNAS gave them, held while they are locked."""

import json

import pytest

from backend.hardware.pal import generic_linux as gl


def test_mount_lookups(tmp_path):
    mounts = tmp_path / "mounts"
    pool = tmp_path / "tank"
    (pool / "photos").mkdir(parents=True)
    mounts.write_text(
        f"tank {pool} zfs rw 0 0\n"
        f"tank/photos {pool}/photos zfs rw 0 0\n"
        f"tank/home\\040movies {pool}/home\\040movies zfs rw 0 0\n"
        f"/dev/sdb1 {tmp_path}/other btrfs rw 0 0\n"
        "junk\n"
    )
    assert gl.zfs_mounts(str(mounts)) == {
        "tank": str(pool),
        "tank/photos": f"{pool}/photos",
        "tank/home movies": f"{pool}/home movies",
    }
    assert gl.zfs_dataset_at(str(pool / "photos"), str(mounts)) == "tank/photos"
    assert gl.zfs_dataset_at(str(pool / "photos" / "2024"), str(mounts)) == ""
    assert gl.zfs_mounts(str(tmp_path / "missing")) == {}


def test_snapshot_names_zfs_accepts():
    assert gl.zfs_snapshot_part("photos@auto-20261103T101500Z") == "photos-auto-20261103T101500Z"
    assert gl.zfs_snapshot_part("a b/c") == "a-b-c"
    assert gl.zfs_snapshot_part("") == "snapshot"


class FakeZfs:
    """zfs create/snapshot/hold/release/destroy/list against a dict, the way the adapter calls it."""

    def __init__(self, pool):
        self.pool = pool
        self.datasets = {"tank": str(pool)}
        self.snaps = {}  # full name -> (creation, label, held)
        self.calls = []
        self.fail = set()

    def __call__(self, cmd):
        self.calls.append(cmd)
        verb = cmd[1]
        if verb in self.fail:
            return 1, "", f"cannot {verb}: permission denied"
        if verb == "create":
            mnt = f"{self.datasets[cmd[2].rsplit('/', 1)[0]]}/{cmd[2].rsplit('/', 1)[1]}"
            (self.pool / cmd[2].rsplit("/", 1)[1]).mkdir()
            self.datasets[cmd[2]] = mnt
        elif verb == "snapshot":
            self.snaps[cmd[-1]] = [str(1793700000 + len(self.snaps)), cmd[3].split("=", 1)[1], False]
        elif verb == "hold":
            self.snaps[cmd[-1]][2] = True
        elif verb == "release":
            if not self.snaps.get(cmd[-1], [0, 0, False])[2]:
                return 1, "", "no such tag on this dataset"
            self.snaps[cmd[-1]][2] = False
        elif verb == "destroy":
            if self.snaps[cmd[-1]][2]:
                return 1, "", "dataset is busy"
            del self.snaps[cmd[-1]]
        elif verb == "list":
            rows = [f"{n}\t{c}\t{lbl}" for n, (c, lbl, _) in self.snaps.items()]
            rows.append("other@x\t1\t-")  # a dataset outside the pool
            return 0, "\n".join(rows), ""
        return 0, "", ""


@pytest.fixture
def zfs(tmp_path, monkeypatch):
    pool = tmp_path / "tank"
    pool.mkdir()
    fake = FakeZfs(pool)
    a = gl.GenericLinuxStorageAdapter(str(pool))
    monkeypatch.setattr(a, "_run_cmd", fake)
    monkeypatch.setattr(gl, "fs_of", lambda path: "zfs")
    monkeypatch.setattr(gl, "zfs_mounts", lambda: {**fake.datasets, "other": "/elsewhere"})
    monkeypatch.setattr(gl, "zfs_dataset_at", lambda path: next((d for d, m in fake.datasets.items() if m == path), ""))
    monkeypatch.setattr(
        "backend.hardware.pal.base.storage_tools", lambda: {"btrfs": False, "zfs": True, "mdadm": False}
    )
    return a, fake, pool


def test_a_new_share_on_zfs_is_a_dataset(zfs):
    a, fake, pool = zfs
    assert a._make_share_dir(str(pool / "photos")) == "dataset"
    assert fake.calls == [["zfs", "create", "tank/photos"]]
    assert a._make_share_dir(str(pool / "photos")) == "folder"  # already there: left alone
    assert len(fake.calls) == 1


def test_a_failed_dataset_becomes_a_plain_folder(zfs):
    a, fake, pool = zfs
    fake.fail.add("create")
    assert a._make_share_dir(str(pool / "docs")) == "folder"
    assert (pool / "docs").is_dir()


def test_snapshots_are_offered_on_a_zfs_pool(zfs):
    a, _, _ = zfs
    assert a.get_capabilities().can_snapshot is True


def test_snapshot_list_and_delete_by_our_own_name(zfs):
    a, fake, pool = zfs
    a._make_share_dir(str(pool / "photos"))
    res = a.create_snapshot("tank", "photos", "photos@auto-20261103T101500Z")
    assert res["status"] == "created" and res["readonly"] is True
    assert res["snapshot"] == f"{pool}/photos/.zfs/snapshot/photos-auto-20261103T101500Z"
    assert [
        "zfs",
        "snapshot",
        "-o",
        "org.zettnas:name=photos@auto-20261103T101500Z",
        "tank/photos@photos-auto-20261103T101500Z",
    ] in fake.calls
    snaps = a.list_snapshots("tank")
    assert [(s["name"], s["path"], s["zfs"]) for s in snaps] == [
        ("photos@auto-20261103T101500Z", res["snapshot"], "tank/photos@photos-auto-20261103T101500Z")
    ]
    assert snaps[0]["created_at"] > 0
    out = a.delete_snapshot("tank", "photos@auto-20261103T101500Z")
    assert out["status"] == "deleted" and not fake.snaps


def test_a_locked_snapshot_is_held_until_it_may_go(zfs):
    a, fake, pool = zfs
    a._make_share_dir(str(pool / "photos"))
    a.create_snapshot("tank", "photos", "photos@locked", worm_mode="governance", retention_days=7)
    full = "tank/photos@photos-locked"
    assert ["zfs", "hold", "zettnas-worm", full] in fake.calls and fake.snaps[full][2]
    snap = a.list_snapshots("tank")[0]
    assert snap["worm_mode"] == "governance" and snap["is_immutable"]
    with pytest.raises(gl.PlatformCapabilityError):
        a.delete_snapshot("tank", "photos@locked")
    meta = pool / "@snapshots" / ".photos@locked.worm.json"
    data = json.loads(meta.read_text())
    data["retention_until"] = 0
    meta.write_text(json.dumps(data))
    assert a.delete_snapshot("tank", "photos@locked")["status"] == "deleted"
    assert ["zfs", "release", "zettnas-worm", full] in fake.calls and not fake.snaps and not meta.exists()


def test_a_hold_that_fails_still_keeps_the_snapshot(zfs):
    a, fake, pool = zfs
    a._make_share_dir(str(pool / "photos"))
    fake.fail.add("hold")
    assert a.create_snapshot("tank", "photos", "p@x", worm_mode="compliance", retention_days=1)["status"] == "created"


def test_a_folder_share_on_zfs_says_why_it_cant_be_snapshotted(zfs):
    a, fake, pool = zfs
    (pool / "loose").mkdir()
    res = a.create_snapshot("tank", "loose", "loose@auto-1")
    assert res["status"] == "error" and "not a ZFS dataset" in res["output"]
    assert not any(c[1] == "snapshot" for c in fake.calls)


def test_without_zfs_tools_nothing_is_asked(tmp_path, monkeypatch):
    a = gl.GenericLinuxStorageAdapter(str(tmp_path))
    calls = []
    monkeypatch.setattr(a, "_run_cmd", lambda cmd: calls.append(cmd) or (0, "", ""))
    monkeypatch.setattr(
        "backend.hardware.pal.base.storage_tools", lambda: {"btrfs": True, "zfs": False, "mdadm": False}
    )
    assert a.list_snapshots("p") == [] and calls == []
