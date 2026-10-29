"""FEAT-10 / REL-19: quotas the filesystem enforces (btrfs qgroup, ZFS refquota, XFS project),
and an honest "checked on uploads only" everywhere else."""

import subprocess

import pytest

from backend.hardware import fs_quota as fq


class Tools:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, cmd, timeout=20, capture_output=True, text=True):
        self.calls.append(cmd)
        key = " ".join(cmd[:3])
        rc = 1 if any(f in key for f in self.fail) else 0
        return subprocess.CompletedProcess(cmd, rc, "", "refused" if rc else "")


def mounts(tmp_path, fstype, options="rw", device="tank/data", at=None):
    return [
        {"device": device, "mountpoint": str(at or tmp_path), "fstype": fstype, "options": options},
        {"device": "overlay", "mountpoint": "/", "fstype": "overlay", "options": "rw"},
    ]


def test_btrfs_subvolume_gets_a_qgroup_limit(tmp_path):
    t = Tools()
    res = fq.apply(str(tmp_path), 10 * 1024**3, t, mounts(tmp_path, "btrfs"))
    assert res == {"enforced": True, "method": "btrfs-qgroup", "reason": ""}
    assert ["btrfs", "qgroup", "limit", str(10 * 1024**3), str(tmp_path)] in t.calls
    fq.apply(str(tmp_path), 0, t, mounts(tmp_path, "btrfs"))
    assert t.calls[-1][3] == "none"


def test_btrfs_plain_folder_and_refusal(tmp_path):
    assert (
        "not a btrfs subvolume"
        in fq.apply(str(tmp_path), 1, Tools(["btrfs subvolume show"]), mounts(tmp_path, "btrfs"))["reason"]
    )
    assert "refused" in fq.apply(str(tmp_path), 1, Tools(["btrfs qgroup limit"]), mounts(tmp_path, "btrfs"))["reason"]


def test_zfs_dataset_gets_refquota(tmp_path):
    t = Tools()
    res = fq.apply(str(tmp_path), 5 * 1024**3, t, mounts(tmp_path, "zfs"))
    assert res["method"] == "zfs-refquota" and ["zfs", "set", f"refquota={5 * 1024**3}", "tank/data"] in t.calls
    fq.apply(str(tmp_path), 0, t, mounts(tmp_path, "zfs"))
    assert t.calls[-1][2] == "refquota=none"
    assert "refused" in fq.apply(str(tmp_path), 1, Tools(["zfs set"]), mounts(tmp_path, "zfs"))["reason"]
    sub = tmp_path / "folder"
    sub.mkdir()
    res = fq.apply(str(sub), 1, Tools(), mounts(tmp_path, "zfs"))
    assert res["enforced"] is False and "limits whole datasets" in res["reason"]


def test_xfs_project_quota(tmp_path):
    t = Tools()
    res = fq.apply(str(tmp_path), 2 * 1024**3, t, mounts(tmp_path, "xfs", "rw,prjquota", "/dev/sdb1"))
    pid = fq.project_id(str(tmp_path))
    assert res["method"] == "xfs-project" and 10000 <= pid < 1000000
    assert t.calls[0] == ["xfs_quota", "-x", "-c", f"project -s -p {tmp_path} {pid}", str(tmp_path)]
    assert t.calls[1][3] == f"limit -p bhard={2 * 1024**3} {pid}"
    no_prj = fq.apply(str(tmp_path), 1, t, mounts(tmp_path, "xfs", "rw,noatime"))
    assert no_prj["enforced"] is False and "prjquota" in no_prj["reason"]
    assert (
        "xfs_quota refused"
        in fq.apply(str(tmp_path), 1, Tools(["xfs_quota -x -c"]), mounts(tmp_path, "xfs", "pquota"))["reason"]
    )


@pytest.mark.parametrize(
    "fstype,word", [("fuse.shfs", "Unraid"), ("ext4", "ext4"), ("nfs4", "network mount"), ("vfat", "vfat")]
)
def test_advisory_elsewhere(tmp_path, fstype, word):
    res = fq.apply(str(tmp_path), 1, Tools(), mounts(tmp_path, fstype))
    assert res["enforced"] is False and word in res["reason"] and "uploads" in res["reason"]


def test_missing_folder_and_missing_tools(tmp_path):
    assert fq.apply(str(tmp_path / "nope"), 1)["reason"] == "The folder doesn't exist."

    def gone(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    assert fq.apply(str(tmp_path), 1, gone, mounts(tmp_path, "btrfs"))["enforced"] is False


def test_zfs_child_dataset(tmp_path):
    t = Tools()
    assert fq.zfs_child_dataset(str(tmp_path), "kid", t, mounts(tmp_path, "zfs")) == str(tmp_path / "kid")
    assert t.calls == [["zfs", "create", "tank/data/kid"]]
    assert fq.zfs_child_dataset(str(tmp_path), "kid", Tools(["zfs create"]), mounts(tmp_path, "zfs")) is None
    assert fq.zfs_child_dataset(str(tmp_path), "kid", t, mounts(tmp_path, "btrfs")) is None
    sub = tmp_path / "homes"
    sub.mkdir()
    assert fq.zfs_child_dataset(str(sub), "kid", t, mounts(tmp_path, "zfs")) is None  # a folder, not a dataset


# --- people's spaces ---


@pytest.fixture
def spaces(tmp_path, monkeypatch):
    from backend import config
    from backend.services import user_spaces as us

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(config, "POOL_PATH", str(tmp_path / "pool"), raising=False)
    monkeypatch.setattr(us, "_btrfs", lambda args: False)
    monkeypatch.setattr(us.fs_quota, "zfs_child_dataset", lambda parent, name: None)
    return us


def test_a_home_records_how_its_limit_is_held(spaces, monkeypatch):
    seen = []
    monkeypatch.setattr(
        spaces.fs_quota,
        "apply",
        lambda home, b: seen.append((home, b)) or {"enforced": True, "method": "zfs-refquota", "reason": ""},
    )
    monkeypatch.setattr(spaces, "home_of", lambda u: str(spaces.homes_root()) + "/" + u)
    out = spaces.ensure_home("kid", 1024)
    assert out["fs_quota"] is True and seen[0][1] == 1024
    assert spaces.enforcement(out["home"])["method"] == "zfs-refquota"
    assert spaces.set_quota("kid", 2048) is True and seen[-1][1] == 2048
    assert spaces.enforcement(out["home"])["quota_bytes"] == 2048
    monkeypatch.setattr(
        spaces.fs_quota, "apply", lambda home, b: {"enforced": False, "method": None, "reason": "ext4 here"}
    )
    assert spaces.set_quota("kid", 4096) is False
    assert spaces.enforcement(out["home"])["enforced"] is False
    assert spaces.set_quota("newkid", 10) is False  # a missing home is made first
    monkeypatch.setattr(spaces, "quota_of", lambda u: 4096)
    assert spaces.summary("kid")["enforcement"]["reason"] == "ext4 here"


def test_a_zfs_homes_folder_gives_each_person_a_dataset(spaces, monkeypatch):
    made = []
    monkeypatch.setattr(
        spaces.fs_quota,
        "zfs_child_dataset",
        lambda parent, name: made.append(name) or (spaces.os.makedirs(f"{parent}/{name}") or f"{parent}/{name}"),
    )
    monkeypatch.setattr(spaces, "home_of", lambda u: str(spaces.homes_root()) + "/" + u)
    assert spaces.ensure_home("teen", 0)["subvolume"] is True and made == ["teen"]


def test_changing_a_quota_reaches_the_filesystem(client, auth_headers, monkeypatch):
    from backend.api import auth as auth_api
    from backend.users_db import create_user, get_user_by_username

    create_user("feat10kid", "Kid", "GoodPass123!", role_id="kid")
    uid = get_user_by_username("feat10kid")["id"]
    applied = []
    monkeypatch.setattr(auth_api, "_apply_quota", lambda u, b: applied.append((u, b)))
    res = client.put(f"/api/users/{uid}", json={"storage_quota_bytes": 5 * 1024**3}, headers=auth_headers)
    assert res.status_code == 200 and applied == [("feat10kid", 5 * 1024**3)]
    client.put(f"/api/users/{uid}", json={"storage_quota_bytes": 5 * 1024**3}, headers=auth_headers)
    assert len(applied) == 1  # unchanged: nothing to do


def test_apply_quota_logs_a_failure(monkeypatch):
    from backend.api import auth as auth_api
    from backend.services import user_spaces

    def boom(u, b):
        raise OSError("read-only file system")

    monkeypatch.setattr(user_spaces, "set_quota", boom)
    auth_api._apply_quota("x", 1)  # logged, not raised
    assert auth_api._quota_enforcement({"storage_quota_bytes": 0}) is None


def test_a_share_quota_goes_to_the_filesystem(tmp_path, monkeypatch):
    from backend.hardware.pal import generic_linux

    seen = []
    monkeypatch.setattr(
        generic_linux.fs_quota,
        "apply",
        lambda path, b: seen.append(b) or {"enforced": True, "method": "btrfs-qgroup", "reason": ""},
    )
    monkeypatch.setattr("backend.services.samba_engine.validate_share_path", lambda p: str(tmp_path / "media"))
    adapter = generic_linux.GenericLinuxStorageAdapter.__new__(generic_linux.GenericLinuxStorageAdapter)
    adapter._pool_path = str(tmp_path)
    res = adapter.create_share(name="media", path="", quota_gb=3, export_smb=False)
    assert seen == [3 * 1024**3] and res["quota_enforcement"]["method"] == "btrfs-qgroup"
