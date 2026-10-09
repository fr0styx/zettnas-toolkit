"""
ZettNAS Toolkit - PAL Storage & Shares Unit & Integration Tests
Verifies Platform Abstraction Layer (PAL), Unraid/Generic Linux adapters,
safe read-only share auditing, and observer mode invariants.
"""

from unittest.mock import patch

from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    PlatformCapabilityError,
    PlatformType,
    StoragePlatformDetector,
    UnraidStorageAdapter,
    get_storage_platform,
)

MOCK_DISKS_INI = """
["parity"]
device="sdb"
id="ST22000DM000_PARITY"
size="21485322188"
transport="ata"
rotational="1"
spundown="1"
status="DISK_OK"
temp="*"
numReads="1000"
numWrites="50"
numErrors="0"
type="Parity"
color="green-blink"

["disk1"]
device="sda"
id="ST22000DM000_DATA1"
size="21485322188"
transport="ata"
rotational="1"
spundown="0"
status="DISK_OK"
temp="42"
numReads="5000"
numWrites="200"
numErrors="0"
type="Data"
color="green-on"
fsType="xfs"
fsMountpoint="/mnt/disk1"
fsSize="21483235276"
fsFree="7236777780"
fsUsed="14246457496"

["ark"]
device="nvme1n1"
id="WD_BLACK_1"
size="976761560"
transport="nvme"
rotational="0"
spundown="0"
status="DISK_OK"
temp="34"
type="Cache"
color="green-on"
fsType="btrfs"
fsMountpoint="/mnt/ark"
fsProfile="raid1"
fsSize="976761560"
fsFree="795579252"
fsUsed="179446492"
nameOrig="ark"
autotrim="on"

["ark2"]
device="nvme2n1"
id="WD_BLACK_2"
size="976761560"
transport="nvme"
rotational="0"
spundown="0"
status="DISK_OK"
temp="35"
type="Cache"
color="green-on"
nameOrig="ark"

["flash"]
device="nvme0n1"
id="BOOT_NVME"
size="250057728"
transport="nvme"
rotational="0"
spundown="0"
status="DISK_OK"
temp="29"
type="Boot"
color="green-on"
fsType="zfs"
fsMountpoint="/boot"
fsSize="239793900"
fsFree="238448620"
fsUsed="1345280"
"""

MOCK_SHARES_INI = """
["appdata"]
comment="application data"
useCache="only"
cachePool="ark"
color="green-on"
free="795579252"
used="179446492"

["vault"]
comment="HDD Array"
useCache="yes"
cachePool="ark"
color="green-on"
free="8032357032"
used="14425903988"
"""

MOCK_SEC_INI = """
["appdata"]
export="e"
security="public"

["vault"]
export="-"
security="private"
"""

MOCK_SEC_NFS_INI = """
["appdata"]
export="-"

["vault"]
export="e"
"""


def test_platform_detector_unraid():
    with patch("backend.hardware.pal_storage._find_emhttp_dir", return_value="/var/local/emhttp"):
        p_type = StoragePlatformDetector.detect()
        assert p_type == PlatformType.UNRAID


def test_platform_detector_generic_linux():
    with (
        patch("backend.hardware.pal_storage._find_emhttp_dir", return_value=None),
        patch("os.path.isfile", return_value=False),
    ):
        p_type = StoragePlatformDetector.detect()
        assert p_type == PlatformType.GENERIC_LINUX


def test_unraid_storage_adapter_observer_mode_invariants():
    adapter = UnraidStorageAdapter()
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_create_pools is False
    assert caps.can_destroy_pools is False
    assert caps.can_manage_shares is False
    assert caps.can_trigger_scrub is True

    # Destructive operations must raise PlatformCapabilityError
    try:
        adapter.create_pool("test", "btrfs", "raid1", ["/dev/sdc"], "/mnt/test")
        assert False, "Should have raised PlatformCapabilityError"
    except PlatformCapabilityError:
        pass

    try:
        adapter.destroy_pool("unraid_array")
        assert False, "Should have raised PlatformCapabilityError"
    except PlatformCapabilityError:
        pass

    try:
        adapter.create_share("test", "/mnt/user/test")
        assert False, "Should have raised PlatformCapabilityError"
    except PlatformCapabilityError:
        pass


def test_unraid_storage_adapter_pools_parsing(tmp_path):
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    (emhttp_dir / "disks.ini").write_text(MOCK_DISKS_INI)
    (emhttp_dir / "var.ini").write_text("mdState=STARTED\nmdColor=green-on\n")

    adapter = UnraidStorageAdapter()
    adapter._emhttp_dir = str(emhttp_dir)

    pools = adapter.list_pools()
    assert len(pools) >= 3

    # Main Array
    array = next(p for p in pools if p.id == "unraid_array")
    assert array.name == "Main Array"
    assert array.parity_protected is True
    assert array.fs_type == "xfs"
    assert len(array.members) == 2  # parity + disk1
    parity_member = next(m for m in array.members if m.role == "parity")
    assert parity_member.spundown is True
    assert parity_member.status == "STANDBY"
    data_member = next(m for m in array.members if m.role == "data")
    assert data_member.spundown is False
    assert data_member.temp_c == 42

    # Cache Pool (ark)
    cache = next(p for p in pools if p.id == "cache_ark")
    assert cache.pool_type == "btrfs_raid"
    assert cache.fs_profile == "raid1"
    assert len(cache.members) == 2  # ark + ark2
    assert cache.autotrim is True

    # Boot Pool
    boot = next(p for p in pools if p.id == "boot_pool")
    assert boot.fs_type == "zfs"
    assert len(boot.members) == 1


def test_unraid_storage_adapter_shares_parsing(tmp_path):
    emhttp_dir = tmp_path / "emhttp"
    emhttp_dir.mkdir()
    (emhttp_dir / "shares.ini").write_text(MOCK_SHARES_INI)
    (emhttp_dir / "sec.ini").write_text(MOCK_SEC_INI)
    (emhttp_dir / "sec_nfs.ini").write_text(MOCK_SEC_NFS_INI)

    adapter = UnraidStorageAdapter()
    adapter._emhttp_dir = str(emhttp_dir)

    shares = adapter.list_shares()
    assert len(shares) == 2

    appdata = next(s for s in shares if s.name == "appdata")
    assert appdata.comment == "application data"
    assert appdata.cache_mode == "only"
    assert appdata.cache_pool == "ark"
    assert appdata.export_smb is True
    assert appdata.export_nfs is False
    assert appdata.export_webdav is True
    assert appdata.security == "public"
    assert appdata.used_bytes > 0
    assert appdata.free_bytes > 0

    vault = next(s for s in shares if s.name == "vault")
    assert vault.comment == "HDD Array"
    assert vault.cache_mode == "yes"
    assert vault.export_smb is False
    assert vault.export_nfs is True
    assert vault.security == "private"


def test_generic_linux_storage_adapter():
    adapter = GenericLinuxStorageAdapter()
    caps = adapter.get_capabilities()
    assert caps.is_observer_mode is False
    assert caps.can_create_pools is True
    assert caps.can_manage_shares is True

    # Creating pool & share succeeds in Generic Linux mode
    res_pool = adapter.create_pool("data_pool", "btrfs", "raid1", ["/dev/sdb", "/dev/sdc"], "/mnt/data")
    assert res_pool["status"] == "provisioned"

    res_share = adapter.create_share("media", "", comment="Media share", security="public")
    assert res_share["status"] == "created"


def test_storage_api_platform_and_pools_endpoints(client, auth_headers):
    response = client.get("/api/storage/platform", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "platform" in data
    assert "capabilities" in data
    assert "is_observer_mode" in data["capabilities"]

    pools_resp = client.get("/api/storage/pools", headers=auth_headers)
    assert pools_resp.status_code == 200
    pools_data = pools_resp.json()
    assert "pools" in pools_data
    assert isinstance(pools_data["pools"], list)


def test_storage_api_shares_endpoint(client, auth_headers):
    response = client.get("/api/storage/shares", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "shares" in data
    assert isinstance(data["shares"], list)


def test_storage_api_observer_mode_rejections(client, auth_headers):
    adapter = get_storage_platform()
    if adapter.get_capabilities().is_observer_mode:
        # Creating a pool should be rejected with 403 Forbidden
        pool_payload = {
            "name": "hacker_pool",
            "fs_type": "btrfs",
            "profile": "raid0",
            "disks": ["/dev/sda"],
            "mountpoint": "/mnt/hacker",
        }
        resp = client.post("/api/storage/pools", json=pool_payload, headers=auth_headers)
        assert resp.status_code == 403

        # Creating a share should be rejected with 403 Forbidden
        share_payload = {
            "name": "hacker_share",
            "path": "/mnt/user/hacker",
            "comment": "forbidden",
            "security": "public",
        }
        resp = client.post("/api/storage/shares", json=share_payload, headers=auth_headers)
        assert resp.status_code == 403
