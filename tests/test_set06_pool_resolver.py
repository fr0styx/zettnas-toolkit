"""SET-06: scrub, eject, rename, remove and the monthly check reach the pool that was named.

Each of them worked a path out of the pool id, as "<pool folder>/<id>". Ids are device names, so
for a btrfs, ext4, XFS or md pool that folder does not exist: every scrub ran on the main pool,
"Destroy" unmounted nothing and answered "destroyed", and a rename that failed said "renamed".
One function now turns an id into the pool, with its kind and its real folder."""

import pytest

from backend.hardware.pal.base import StoragePool
from backend.hardware.pal_storage import GenericLinuxStorageAdapter


def _pool(pool_id, fs_type, mountpoint, name=None):
    kind = {"zfs": "zfs_pool", "btrfs": "btrfs_raid"}.get(fs_type, "single")
    return StoragePool(id=pool_id, name=name or pool_id, pool_type=kind, fs_type=fs_type, mountpoint=mountpoint)


POOLS = [
    _pool("default_pool", "btrfs", "/mnt/storage", "Primary Storage Pool"),
    _pool("sdc1", "btrfs", "/mnt/pools/media", "media"),
    _pool("tank", "zfs", "/mnt/tank"),
    _pool("md0", "ext4", "/mnt/pools/archive", "archive"),
]


@pytest.fixture
def system(tmp_path):
    """A NAS with two btrfs pools, a ZFS pool and an md pool; `ran` collects the commands."""
    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")
    ran = []
    fail = set()

    def run(cmd):
        ran.append(cmd)
        if cmd[0] == "fuser":
            return 1, "", ""  # nothing holds the folder open
        return (1, "", "it did not work") if cmd[0] in fail else (0, "ok", "")

    adapter._run_cmd = run
    adapter.list_pools = lambda: list(POOLS)
    return adapter, ran, fail


@pytest.mark.parametrize(
    "pool_id, found",
    [
        ("sdc1", "sdc1"),
        ("tank", "tank"),
        ("zfs:tank", "tank"),  # what older callers sent
        ("md0", "md0"),
        ("media", "sdc1"),  # by the name it shows
        ("default", "default_pool"),
        ("", "default_pool"),
        ("default_pool", "default_pool"),
    ],
)
def test_an_id_finds_its_pool(system, pool_id, found):
    adapter, _ran, _fail = system
    assert adapter.resolve_pool(pool_id).id == found


def test_the_main_pool_is_always_found(system, monkeypatch):
    adapter, _ran, _fail = system
    adapter.list_pools = lambda: [POOLS[1], POOLS[2]]  # a list that shows no "default_pool"
    monkeypatch.setattr(
        adapter, "_parse_mounts", lambda: [{"device": "/dev/sda1", "mountpoint": "/mnt/storage", "fstype": "btrfs"}]
    )
    main = adapter.resolve_pool("default")
    assert (main.id, main.fs_type, main.mountpoint) == ("default_pool", "btrfs", "/mnt/storage")
    adapter.list_pools = lambda: [_pool("sda1", "btrfs", "/mnt/storage", "Main")]  # or shows it under its device
    assert adapter.resolve_pool("default").id == "sda1"


def test_an_unknown_id_finds_nothing_and_runs_nothing(system):
    adapter, ran, _fail = system
    for act in (
        lambda: adapter.trigger_scrub("sdz9"),
        lambda: adapter.destroy_pool("sdz9"),
        lambda: adapter.export_pool("sdz9"),
        lambda: adapter.rename_pool("sdz9", "new"),
    ):
        with pytest.raises(LookupError):
            act()
    assert ran == []


def test_scrub_runs_on_the_pool_that_was_named(system):
    adapter, ran, _fail = system
    res = adapter.trigger_scrub("sdc1")
    assert ran == [["btrfs", "scrub", "start", "/mnt/pools/media"]]  # not the main pool
    assert res["status"] == "started" and res["message"] == "The check of media was started."
    ran.clear()
    assert adapter.trigger_scrub("tank")["status"] == "started"
    assert ran == [["zpool", "scrub", "tank"]]
    ran.clear()
    assert adapter.trigger_scrub("default")["status"] == "started"
    assert ran == [["btrfs", "scrub", "start", "/mnt/storage"]]
    ran.clear()
    adapter.trigger_scrub("sdc1", "cancel")
    adapter.trigger_scrub("tank", "cancel")
    assert ran == [["btrfs", "scrub", "cancel", "/mnt/pools/media"], ["zpool", "scrub", "-s", "tank"]]


def test_a_pool_with_no_check_of_its_own_says_so(system):
    adapter, ran, _fail = system
    res = adapter.trigger_scrub("md0")
    assert res["status"] == "unsupported" and "archive is ext4" in res["message"]
    assert ran == []


def test_a_scrub_that_did_not_start_does_not_say_it_did(system):
    adapter, _ran, fail = system
    fail.add("btrfs")
    res = adapter.trigger_scrub("sdc1")
    assert res["status"] == "error" and res["message"] == "The check of media could not be started."


def test_remove_unmounts_the_named_pool_and_fails_when_it_cannot(system):
    adapter, ran, fail = system
    res = adapter.destroy_pool("md0")
    assert ran == [["umount", "-f", "/mnt/pools/archive"]] and res["status"] == "destroyed"
    fail.add("umount")
    with pytest.raises(RuntimeError, match="archive could not be unmounted"):
        adapter.destroy_pool("md0")


def test_eject_uses_the_pools_own_folder(system):
    adapter, ran, _fail = system
    adapter.export_pool("sdc1", force=True)
    assert ["umount", "-f", "/mnt/pools/media"] in ran
    assert not any(c[:2] == ["zpool", "export"] for c in ran)
    ran.clear()
    adapter.export_pool("tank")
    assert ["zpool", "export", "tank"] in ran


def test_rename_sets_the_label_on_the_named_pool_and_fails_when_it_cannot(system):
    adapter, ran, fail = system
    res = adapter.rename_pool("sdc1", "films")
    assert ran == [["btrfs", "filesystem", "label", "/mnt/pools/media", "films"]]
    assert res["status"] == "renamed" and res["old_name"] == "media" and res["new_name"] == "films"
    fail.add("btrfs")
    with pytest.raises(RuntimeError, match="media could not be renamed"):
        adapter.rename_pool("sdc1", "films")
    with pytest.raises(ValueError, match="only ZFS and btrfs"):
        adapter.rename_pool("md0", "old-archive")


def test_the_routes_answer_what_happened(client, auth_headers, system, monkeypatch):
    adapter, ran, fail = system
    monkeypatch.setattr("backend.api.storage.get_storage_platform", lambda: adapter)
    monkeypatch.setattr(type(adapter), "get_capabilities", lambda self: _Caps())
    r = client.post("/api/storage/scrub", json={"pool_id": "sdc1", "action": "start"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["message"] == "The check of media was started."
    r = client.post("/api/storage/scrub", json={"pool_id": "md0", "action": "start"}, headers=auth_headers)
    assert r.status_code == 400 and "no check of its own" in r.json()["detail"]
    r = client.post("/api/storage/scrub", json={"pool_id": "sdz9", "action": "start"}, headers=auth_headers)
    assert r.status_code == 404
    fail.add("btrfs")
    r = client.post("/api/storage/scrub", json={"pool_id": "sdc1", "action": "start"}, headers=auth_headers)
    assert r.status_code == 502 and "could not be started" in r.json()["detail"]
    r = client.post("/api/storage/pools/sdc1/rename", json={"new_name": "films"}, headers=auth_headers)
    assert r.status_code == 409 and "could not be renamed" in r.json()["detail"]
    fail.add("umount")
    r = client.delete("/api/storage/pools/md0", headers=auth_headers)
    assert r.status_code == 409 and "could not be unmounted" in r.json()["detail"]


class _Caps:
    is_observer_mode = False
    can_trigger_scrub = True
    can_export_pools = True
    can_destroy_pools = True
