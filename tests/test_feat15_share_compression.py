"""FEAT-15: compression per share, read from the filesystem, and pool rows that say what the
pool really uses instead of assuming zstd."""

import subprocess
from types import SimpleNamespace

import pytest

from backend.hardware import share_compression as sc

MOUNTS = [
    {"device": "tank/media", "mountpoint": "/mnt/tank/media", "fstype": "zfs", "options": "rw,xattr"},
    {"device": "tank", "mountpoint": "/mnt/tank", "fstype": "zfs", "options": "rw"},
    {
        "device": "/dev/sdb1",
        "mountpoint": "/mnt/pool",
        "fstype": "btrfs",
        "options": "rw,noatime,compress=zstd:3,space_cache=v2",
    },
    {"device": "/dev/sdc1", "mountpoint": "/mnt/plain", "fstype": "btrfs", "options": "rw,noatime"},
    {"device": "/dev/sdd1", "mountpoint": "/mnt/xfs", "fstype": "xfs", "options": "rw"},
    {"device": "overlay", "mountpoint": "/", "fstype": "overlay", "options": "rw"},
]


class FakeTools:
    """zfs and btrfs as recorded calls with canned answers."""

    def __init__(self):
        self.zfs = {
            "tank/media": {"compression": "lz4", "compressratio": "1.52x"},
            "tank": {"compression": "zstd", "compressratio": "1.10x"},
        }
        self.btrfs = {}
        self.calls = []
        self.fail = False

    def __call__(self, cmd, timeout, capture_output=True, text=True):
        self.calls.append(cmd)
        if self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", "operation not permitted")
        if cmd[:2] == ["zfs", "get"]:
            ds = cmd[-1]
            if ds not in self.zfs:
                return subprocess.CompletedProcess(cmd, 1, "", "dataset does not exist")
            props = cmd[-2].split(",")
            out = "".join(f"{p}\t{self.zfs[ds][p]}\n" for p in props)
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd[:2] == ["zfs", "set"]:
            key, _, value = cmd[2].partition("=")
            self.zfs[cmd[3]][key] = value
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[:3] == ["btrfs", "property", "get"]:
            v = self.btrfs.get(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, f"compression={v}\n" if v else "", "")
        if cmd[:3] == ["btrfs", "property", "set"]:
            self.btrfs[cmd[3]] = cmd[5]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)


@pytest.fixture
def tools(monkeypatch):
    monkeypatch.setattr(sc, "read_mounts", lambda path=sc.MOUNTS: [dict(m) for m in MOUNTS])
    monkeypatch.setattr(sc, "_realpath", lambda p: p.rstrip("/") or "/")
    sc._POOL_CACHE.clear()
    return FakeTools()


def test_mount_options_and_the_mounts_file(tmp_path):
    assert sc.btrfs_mount_option("rw,compress=zstd:3") == "zstd:3"
    assert sc.btrfs_mount_option("rw,compress-force=lzo") == "lzo"
    assert sc.btrfs_mount_option("rw,compress=no") == "off"
    assert sc.btrfs_mount_option("rw,noatime") == "off"
    f = tmp_path / "mounts"
    f.write_text("tank/my\\040files /mnt/my\\040files zfs rw 0 0\nshort line\n")
    assert sc.read_mounts(str(f)) == [
        {"device": "tank/my files", "mountpoint": "/mnt/my files", "fstype": "zfs", "options": "rw"}
    ]
    assert sc.read_mounts(str(tmp_path / "missing")) == []


def test_the_longest_mount_wins(tools):
    assert sc.mount_for("/mnt/tank/media/films")["device"] == "tank/media"
    assert sc.mount_for("/mnt/tank/other")["device"] == "tank"
    assert sc.mount_for("/srv")["fstype"] == "overlay"


def test_a_zfs_share_that_is_its_own_dataset(tools):
    info = sc.read("/mnt/tank/media", run=tools)
    assert info["value"] == "lz4" and info["ratio"] == 1.52 and info["own_dataset"] is True
    assert info["choices"][0] == "off"
    out = sc.set_value("/mnt/tank/media", "zstd", run=tools)
    assert ["zfs", "set", "compression=zstd", "tank/media"] in tools.calls
    assert out["value"] == "zstd"


def test_a_zfs_share_inside_a_bigger_dataset_is_not_changed_for_everyone(tools):
    info = sc.read("/mnt/tank/photos", run=tools)
    assert info["own_dataset"] is False and "whole dataset tank" in info["note"]
    with pytest.raises(sc.CompressionError, match="per dataset"):
        sc.set_value("/mnt/tank/photos", "zstd", run=tools)
    assert not any(c[:2] == ["zfs", "set"] for c in tools.calls)


def test_btrfs_folder_setting_over_the_mount_option(tools):
    info = sc.read("/mnt/pool/docs", run=tools)
    assert info["value"] == "zstd:3" and info["from_mount"] is True and info["ratio"] is None
    out = sc.set_value("/mnt/pool/docs", "lzo", run=tools)
    assert ["btrfs", "property", "set", "/mnt/pool/docs", "compression", "lzo"] in tools.calls
    assert out["value"] == "lzo" and out["from_mount"] is False
    sc.set_value("/mnt/pool/docs", "off", run=tools)
    assert tools.btrfs["/mnt/pool/docs"] == "none"
    assert sc.read("/mnt/pool/docs", run=tools)["value"] == "off"


def test_a_sleeping_disk_is_not_read_or_written(tools):
    info = sc.read("/mnt/pool/docs", asleep=lambda p: True, run=tools)
    assert info["asleep"] is True and info["value"] == "zstd:3"
    assert not any(c[:2] == ["btrfs", "property"] for c in tools.calls)
    with pytest.raises(sc.CompressionError, match="asleep"):
        sc.set_value("/mnt/pool/docs", "zstd", asleep=lambda p: True, run=tools)


def test_what_cant_be_set(tools):
    xfs = sc.read("/mnt/xfs/a", run=tools)
    assert xfs["supported"] is False and "xfs has no compression" in xfs["reason"]
    with pytest.raises(sc.CompressionError, match="no compression"):
        sc.set_value("/mnt/xfs/a", "zstd", run=tools)
    with pytest.raises(sc.CompressionError, match="Choose one of"):
        sc.set_value("/mnt/pool/docs", "lz4", run=tools)  # lz4 is ZFS only
    tools.zfs.pop("tank/media")
    assert sc.read("/mnt/tank/media", run=tools)["supported"] is False
    tools.fail = True
    with pytest.raises(sc.CompressionError, match="not permitted"):
        sc.set_value("/mnt/pool/docs", "zstd", run=tools)


def test_missing_tools_are_a_failed_read_not_a_crash(tools):
    def missing(cmd, **kw):
        raise FileNotFoundError(cmd[0])

    assert sc.read("/mnt/tank/media", run=missing)["supported"] is False
    assert sc._pool_compression("zfs", "/mnt/tank", "tank", run=missing) is None


def test_pool_rows_say_what_is_really_used(tools):
    assert sc._pool_compression("zfs", "/mnt/tank", "tank", run=tools) == "zstd"
    assert sc._pool_compression("btrfs", "/mnt/pool", run=tools) == "zstd:3"
    assert sc._pool_compression("btrfs", "/mnt/plain", run=tools) == "off"
    assert sc._pool_compression("btrfs", "/mnt/not-mounted-here", run=tools) is None
    assert sc._pool_compression("xfs", "/mnt/xfs", run=tools) == "off"
    assert sc._pool_compression("", "/mnt/x", run=tools) is None


def test_pool_reads_are_cached(tools, monkeypatch):
    seen = []
    monkeypatch.setattr(sc, "_pool_compression", lambda *a: seen.append(a) or "lz4")
    assert sc.pool_compression("zfs", "/mnt/tank", "tank") == "lz4"
    assert sc.pool_compression("zfs", "/mnt/tank", "tank") == "lz4"
    assert len(seen) == 1
    monkeypatch.setattr(sc.time, "monotonic", lambda: 1e12)
    sc.pool_compression("zfs", "/mnt/tank", "tank")
    assert len(seen) == 2


# --- the API ---


def _adapter(observer=False, shares=("media",)):
    share = [SimpleNamespace(name=n, mountpoint=f"/mnt/tank/{n}") for n in shares]
    return SimpleNamespace(
        list_shares=lambda: share,
        get_capabilities=lambda: SimpleNamespace(is_observer_mode=observer),
        get_platform_type=lambda: SimpleNamespace(value="unraid" if observer else "generic"),
    )


@pytest.fixture
def api_tools(tools, monkeypatch):
    from backend.api import storage

    monkeypatch.setattr(sc, "run_bounded", tools)
    monkeypatch.setattr(storage, "_share_asleep", lambda p: False)
    for fn in ("read", "set_value"):
        orig = getattr(sc, fn)
        monkeypatch.setattr(sc, fn, lambda *a, _o=orig, **k: _o(*a, **{**k, "run": tools}))
    monkeypatch.setattr(storage, "get_storage_platform", lambda: _adapter())
    return storage


def test_api_reads_and_changes_a_share(client, auth_headers, api_tools):
    res = client.get("/api/storage/shares/media/compression", headers=auth_headers)
    assert res.status_code == 200 and res.json()["value"] == "lz4"
    res = client.put("/api/storage/shares/media/compression", json={"value": "zstd"}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["value"] == "zstd"
    assert (
        client.put("/api/storage/shares/media/compression", json={"value": "brotli"}, headers=auth_headers).status_code
        == 409
    )
    assert (
        client.put("/api/storage/shares/media/compression", json={"value": "ZSTD!"}, headers=auth_headers).status_code
        == 422
    )
    assert client.get("/api/storage/shares/nope/compression", headers=auth_headers).status_code == 404


def test_api_leaves_the_host_to_manage_it_in_observer_mode(client, auth_headers, api_tools, monkeypatch):
    monkeypatch.setattr(api_tools, "get_storage_platform", lambda: _adapter(observer=True))
    info = client.get("/api/storage/shares/media/compression", headers=auth_headers).json()
    assert info["read_only"] is True and "unraid" in info["reason"]
    assert (
        client.put("/api/storage/shares/media/compression", json={"value": "zstd"}, headers=auth_headers).status_code
        == 403
    )


def test_api_share_asleep_check_never_raises(monkeypatch):
    from backend.api import storage
    from backend.services import rag_standby

    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    assert storage._share_asleep("/mnt/x") is False
    monkeypatch.setattr(rag_standby, "is_backing_disk_in_standby", lambda p: True)
    assert storage._share_asleep("/mnt/x") is True


def test_md_and_unraid_cache_pool_rows(tools, monkeypatch):
    seen = []
    monkeypatch.setattr(sc, "pool_compression", lambda *a: seen.append(a) or "zstd")
    assert sc.md_compression("btrfs", "/mnt/md0") == "zstd"
    sc.md_compression("ext4", "/mnt/md1")
    assert seen == [("btrfs", "/mnt/md0"), ("", "/mnt/md1")]
    from backend.hardware.pal import unraid

    monkeypatch.setattr(unraid, "pool_compression", lambda *a: a)
    assert unraid._cache_pool_compression({"fs_type": "zfs"}, "cache") == ("zfs", "/mnt/cache", "cache")
    assert unraid._cache_pool_compression({"mountpoint": "/mnt/fast"}, "fast") == ("btrfs", "/mnt/fast", "fast")
