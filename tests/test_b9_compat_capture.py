"""B9: the recording tool keeps what Kiboto reads and nothing that says whose box it was; TrueNAS
recordings replay through Kiboto's own TrueNAS client."""

import importlib.util
import json
import pathlib

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("compat_capture", ROOT / "scripts" / "compat_capture.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

VAR = """version="7.2.4"
NAME="Smithbox"
regTo="jane@example.com"
SYS_MODEL="D6U"
mdState="STARTED"
mdNumDisks="2"
mdResyncSize="11718885324"
shareCachePool="fastpool"
"""
DISKS = """["parity"]
name="parity"
device="sdb"
id="WDC_WD40EFRX-68N32N0_WD-WCC7K1234567"
size="3907018532"
temp="38"
numReads="123456"
type="Parity"
["disk1"]
name="disk1"
device="sda"
id="ST4000VN008-2DR166_ZDH1ABCD"
size="3907018532"
fsSize="3906988012"
fsUsed="2100000000"
fsFree="1806988012"
fsMountpoint="/mnt/disk1"
type="Data"
["fastpool"]
name="fastpool"
device="nvme0n1"
id="Samsung_SSD_980_S64DNX0R123456"
fsMountpoint="/mnt/fastpool"
fsType="btrfs"
"""
SHARES = """["janes-photos"]
name="janes-photos"
comment="Jane's family photos"
cachePool="fastpool"
useCache="yes"
size="0"
"""


def test_unraid_keeps_the_shape_and_drops_who(tmp_path):
    src = tmp_path / "emhttp"
    src.mkdir()
    (src / "var.ini").write_text(VAR)
    (src / "disks.ini").write_text(DISKS)
    (src / "shares.ini").write_text(SHARES)
    folder = pathlib.Path(cc.capture_unraid(str(src), str(tmp_path / "out")))
    assert folder.parent.name == "7.2.4"
    text = "".join((folder / f).read_text() for f in ("var.ini", "disks.ini", "shares.ini"))
    for secret in (
        "Smithbox",
        "jane",
        "Jane",
        "WCC7K1234567",
        "ZDH1ABCD",
        "S64DNX0R123456",
        "fastpool",
        "123456",
        "11718885324",
        "2100000000",
        "38",
    ):
        assert secret not in text, secret
    assert 'NAME="tower"' in text and '["share_1"]' in text and '["pool_1"]' in text
    assert 'cachePool="pool_1"' in text and 'shareCachePool="pool_1"' in text  # the same fake everywhere
    assert 'fsMountpoint="/mnt/pool_1"' in text and 'mdState="STARTED"' in text and 'SYS_MODEL="D6U"' in text
    assert "regTo" not in text
    ids = [ln for ln in text.splitlines() if ln.startswith("id=")]
    assert ids and all(ln.startswith('id="DISK-') for ln in ids) and len(set(ids)) == len(ids)


def test_unraid_needs_var_ini(tmp_path):
    with pytest.raises(SystemExit, match="no var.ini"):
        cc.capture_unraid(str(tmp_path), str(tmp_path / "out"))


TRUENAS = {
    "/system/info": {"version": "TrueNAS-SCALE-25.10.3", "hostname": "smith-nas"},
    "/pool": [
        {
            "name": "tank",
            "status": "ONLINE",
            "healthy": True,
            "size": 123,
            "allocated": 45,
            "free": 78,
            "topology": {"data": [{"serial": "ZDH1ABCD"}]},
        }
    ],
    "/pool/dataset?limit=500": [
        {"id": "tank", "pool": "tank", "mountpoint": "/mnt/tank", "type": "FILESYSTEM"},
        {
            "id": "tank/janes-photos",
            "pool": "tank",
            "mountpoint": "/mnt/tank/janes-photos",
            "type": "FILESYSTEM",
            "comments": "Jane",
        },
        {"id": "tank/vm-disk", "pool": "tank", "mountpoint": None, "type": "VOLUME"},
    ],
    "/sharing/smb": [
        {"name": "Photos of Jane", "path": "/mnt/tank/janes-photos", "enabled": True, "comment": "private"}
    ],
    "/sharing/nfs": [{"path": "/mnt/tank/janes-photos", "enabled": False, "networks": ["192.168.50.0/24"]}],
    "/zfs/snapshot?limit=5000": [{"name": "tank/janes-photos@before-jane-moved", "dataset": "tank/janes-photos"}],
}


def test_truenas_records_and_replays_through_kibotos_client(tmp_path, monkeypatch):
    folder = pathlib.Path(cc.capture_truenas("https://x", "key", str(tmp_path / "truenas"), get=lambda p: TRUENAS[p]))
    assert folder.name == "25.10.3"
    text = "".join(f.read_text() for f in folder.iterdir())
    for secret in ("tank", "jane", "Jane", "smith", "ZDH1ABCD", "192.168", "private", "123"):
        assert secret not in text, secret
    replay_truenas(folder, monkeypatch)


def replay_truenas(folder: pathlib.Path, monkeypatch):
    """Kiboto's TrueNAS client over one recording: every list parses and matches what was recorded."""
    from backend import settings as _settings
    from backend.hardware.pal import truenas_api

    files = {
        path.split("?")[0]: json.loads((folder / name).read_text()) for name, (path, _k) in cc.TRUENAS_PATHS.items()
    }
    monkeypatch.setenv("TRUENAS_API_KEY", "test-key")
    real = _settings.current
    monkeypatch.setattr(_settings, "current", lambda k: "https://truenas.test" if k == "truenas_url" else real(k))
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=files[req.url.path.removeprefix("/api/v2.0")]))
    pools = truenas_api.pools(transport)
    assert [p["name"] for p in pools] == [p["name"] for p in files["/pool"]]
    datasets = truenas_api.datasets(transport)
    assert len(datasets) == sum(1 for d in files["/pool/dataset"] if d.get("type") == "FILESYSTEM")
    shares = truenas_api.shares(transport)
    assert len(shares) == len(files["/sharing/smb"]) + len(files["/sharing/nfs"])
    snaps = truenas_api.list_snapshots(transport)
    assert len(snaps) == len(files["/zfs/snapshot"]) and all(s["dataset"] and s["name"] for s in snaps)


@pytest.mark.parametrize("folder", sorted((ROOT / "tests" / "compat" / "truenas").glob("*/")), ids=lambda p: p.name)
def test_every_truenas_recording_replays(folder, monkeypatch):
    replay_truenas(folder, monkeypatch)


spec2 = importlib.util.spec_from_file_location("compat_trains", ROOT / "scripts" / "compat_trains.py")
ct = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(ct)


def test_release_lines_and_the_report():
    feed = [
        {"version": "7.3.4"},
        {"version": "7.3.3"},
        {"version": "7.2.9"},
        {"version": "7.4.0-beta.1"},
        {"version": "6.12.15"},
    ]
    assert ct.unraid_lines(feed) == ["7.3", "7.2", "6.12"]
    tags = [
        {"name": "TS-27.0.0-RC.1"},
        {"name": "TS-26.0.0-BETA.3"},
        {"name": "TS-25.10.8"},
        {"name": "TS-25.04.2.6"},
        {"name": "TrueNAS-9.10.2-U5"},
    ]
    assert ct.truenas_lines(tags) == ["25.10", "25.04"]
    text, missing = ct.report(["7.3", "7.2"], ["25.10", "25.04"], {"7.3"}, set())
    assert "| Unraid | 7.3 | yes |" in text and "| TrueNAS | 25.10 | **none yet** |" in text and not missing
    assert ct.report(["7.4", "7.3"], [], {"7.3"}, set())[1] is True  # a new Unraid line without one fails
    assert ct.line("7.3.4") == "7.3" and ct.line("odd") == ""
    assert "7.3" in ct.recorded("unraid")
