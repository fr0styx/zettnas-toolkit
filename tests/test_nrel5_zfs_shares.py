"""NREL-5: on a ZFS pool a new share is a dataset of its own, and its snapshots are ZFS snapshots
under the names Kiboto gave them, held while they are locked."""

import json
import os

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
        if cmd[0] == "cp":  # cp -a src/. dst
            import shutil

            if "cp" in self.fail:
                return 1, "", "no space left"
            shutil.copytree(cmd[2].rstrip("."), cmd[3], dirs_exist_ok=True)
            return 0, "", ""
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
            if cmd[-1] in self.datasets:  # a dataset (-r): its folder goes too
                import shutil

                shutil.rmtree(self.datasets.pop(cmd[-1]), ignore_errors=True)
                return 0, "", ""
            if self.snaps[cmd[-1]][2]:
                return 1, "", "dataset is busy"
            del self.snaps[cmd[-1]]
        elif verb == "rename":
            import os

            old, new = cmd[2], cmd[3]
            target = f"{self.datasets[new.rsplit('/', 1)[0]]}/{new.rsplit('/', 1)[1]}"
            if os.path.exists(target):
                return 1, "", "mountpoint busy"
            os.rename(self.datasets.pop(old), target)
            self.datasets[new] = target
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


def _folder_share(pool, name="docs"):
    share = pool / name
    (share / "sub").mkdir(parents=True)
    (share / "a.txt").write_text("hello")
    (share / "sub" / "b.txt").write_text("world")
    return share


def test_a_folder_share_on_zfs_can_become_a_dataset(zfs):
    a, fake, pool = zfs
    share = _folder_share(pool)
    assert a.can_convert(str(share)) is True
    old = a.convert_to_subvolume(str(share))
    assert fake.datasets["tank/docs"] == str(share) and (share / "sub" / "b.txt").read_text() == "world"
    assert old.startswith(str(pool / "docs.before-dataset-")) and (pool / old.rsplit("/", 1)[1] / "a.txt").exists()
    assert a.can_convert(str(share)) is False  # a dataset now
    assert not any(k.startswith("tank/docs.dataset-") for k in fake.datasets)


def test_a_failed_copy_or_rename_leaves_the_share_as_it_was(zfs):
    a, fake, pool = zfs
    share = _folder_share(pool)
    fake.fail.add("cp")
    with pytest.raises(RuntimeError, match="copied"):
        a.convert_to_subvolume(str(share))
    assert (share / "a.txt").exists() and set(fake.datasets) == {"tank"}
    fake.fail = {"rename"}
    with pytest.raises(RuntimeError, match="place"):
        a.convert_to_subvolume(str(share))
    assert (share / "a.txt").exists() and set(fake.datasets) == {"tank"}
    fake.fail = {"create"}
    with pytest.raises(RuntimeError, match="made"):
        a.convert_to_subvolume(str(share))


def test_no_room_or_no_dataset_above_changes_nothing(zfs, monkeypatch):
    a, fake, pool = zfs
    share = _folder_share(pool)
    monkeypatch.setattr(gl.shutil, "disk_usage", lambda p: type("U", (), {"free": 3})())
    with pytest.raises(RuntimeError, match="free space"):
        a.convert_to_subvolume(str(share))
    nested = pool / "x" / "y"
    nested.mkdir(parents=True)
    assert a.can_convert(str(nested)) is False  # its parent is a plain folder
    with pytest.raises(RuntimeError, match="isn't a ZFS dataset"):
        a._convert_to_dataset(str(nested))
    assert not fake.calls


def test_a_zfs_snapshot_that_reads_empty_is_mounted_to_be_read(zfs, tmp_path, monkeypatch):
    a, fake, pool = zfs
    monkeypatch.setattr(gl, "SNAPSHOT_VIEWS", str(tmp_path / "views"))
    mounted = set()
    monkeypatch.setattr(gl, "is_mount_point", lambda p: p in mounted)
    folder = pool / "photos" / ".zfs" / "snapshot" / "photos-auto-1"
    folder.mkdir(parents=True)
    snap = {"name": "photos@auto-1", "path": str(folder), "zfs": "tank/photos@photos-auto-1"}
    assert a.readable_snapshot_path({"name": "x", "path": "/somewhere"}) == "/somewhere"  # btrfs: as it is
    view = a.readable_snapshot_path(snap)
    assert view == str(tmp_path / "views" / "tank_photos_photos-auto-1")
    assert ["mount", "-t", "zfs", "-o", "ro", "tank/photos@photos-auto-1", view] in fake.calls
    mounted.add(view)
    calls = len(fake.calls)
    assert a.readable_snapshot_path(snap) == view and len(fake.calls) == calls  # mounted once
    (folder / "a.jpg").write_text("x")  # where .zfs/snapshot works (on the host), it is used
    assert a.readable_snapshot_path(snap) == str(folder)


def test_a_snapshot_that_cant_be_mounted_says_so(zfs, tmp_path, monkeypatch):
    a, fake, pool = zfs
    monkeypatch.setattr(gl, "SNAPSHOT_VIEWS", str(tmp_path / "views"))
    monkeypatch.setattr(a, "_run_cmd", lambda cmd: (32, "", "permission denied"))
    with pytest.raises(RuntimeError, match="can't be read here"):
        a.readable_snapshot_path({"path": str(tmp_path / "nope"), "zfs": "tank/p@s"})


def test_a_mounted_snapshot_is_unmounted_before_it_is_destroyed(zfs, tmp_path, monkeypatch):
    a, fake, pool = zfs
    monkeypatch.setattr(gl, "SNAPSHOT_VIEWS", str(tmp_path / "views"))
    a._make_share_dir(str(pool / "photos"))
    a.create_snapshot("tank", "photos", "photos@auto-1")
    full = next(iter(fake.snaps))
    view = a._view_dir(full)
    (tmp_path / "views").mkdir()
    (tmp_path / "views" / os.path.basename(view)).mkdir()
    monkeypatch.setattr(gl, "is_mount_point", lambda p: p == view)
    assert a.delete_snapshot("tank", "photos@auto-1")["status"] == "deleted"
    verbs = [c[0] if c[0] == "umount" else c[1] for c in fake.calls]
    assert verbs.index("umount") < verbs.index("destroy") and not os.path.exists(view)
