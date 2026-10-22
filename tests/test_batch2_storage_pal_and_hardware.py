"""
ZettNAS Toolkit - Batch 2 Test Suite: Storage PAL, Hardware Orchestration & Thermal Safety
Verifies eMMC flash isolation, ZFS/Btrfs member and chunk parsing, TrueNAS/Proxmox observer
adapters, PAL busy interlock, LED speed fix, 16bpp LCD mode, and UPS container preservation.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.hardware.hal import DiskDiscoveryHAL, PhysicalDiskRecord
from backend.hardware.led import find_led_port, send_led_packet
from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    PlatformCapabilityError,
    PlatformType,
    ProxmoxStorageAdapter,
    StoragePlatformDetector,
    TrueNASStorageAdapter,
    get_storage_platform,
)
from backend.services.lcd_renderer import discover_fb_bpp, discover_fb_geometry
from backend.services.ups_watchdog import graceful_docker_teardown


def test_emmc_isolation_and_role_classification():
    """Verifies mmcblk devices are classified as transport='mmc', role='os', and smart_protocol='none'."""
    mock_lsblk = {
        "blockdevices": [
            {"name": "sda", "type": "disk", "rota": True, "size": 4000787030016},
            {"name": "nvme0n1", "type": "disk", "rota": False, "size": 1000204886016},
            {"name": "mmcblk0", "type": "disk", "rota": False, "size": 31268536320},
            {"name": "mmcblk0boot0", "type": "disk", "rota": False, "size": 4194304},
            {"name": "mmcblk0rpmb", "type": "disk", "rota": False, "size": 4194304},
            {"name": "loop0", "type": "disk", "rota": False, "size": 104857600},
        ]
    }

    with patch("subprocess.run") as mock_run, patch.object(DiskDiscoveryHAL, "_read_by_id_links", return_value={}):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"blockdevices": []}', stderr="")
        with patch("json.loads", return_value=mock_lsblk):
            records = DiskDiscoveryHAL.discover_physical_disks(force=True)

    dev_names = [r.dev_name for r in records]
    assert "sda" in dev_names
    assert "nvme0n1" in dev_names
    assert "mmcblk0" in dev_names
    # Boot and RPMB internal partitions must be filtered out
    assert "mmcblk0boot0" not in dev_names
    assert "mmcblk0rpmb" not in dev_names
    assert "loop0" not in dev_names

    mmc_rec = next(r for r in records if r.dev_name == "mmcblk0")
    assert mmc_rec.transport == "mmc"
    assert mmc_rec.role == "os"
    assert mmc_rec.smart_protocol == "none"

    data_rec = next(r for r in records if r.dev_name == "sda")
    assert data_rec.role == "data"


def test_zpool_status_member_parsing():
    """Verifies _parse_zpool_members correctly parses zpool status -P output."""
    sample_zstat = """
  pool: tank
 state: ONLINE
  scan: scrub repaired 0B in 00:02:15 with 0 errors
config:

\tNAME                                                 STATE     READ WRITE CKSUM
\ttank                                                 ONLINE       0     0     0
\t  raidz1-0                                           ONLINE       0     0     0
\t    /dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-1    ONLINE       0     0     0
\t    /dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-2    ONLINE       0     0     0
\t    /dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-3    ONLINE       1     0     2
\tlogs
\t  /dev/nvme0n1p1                                     ONLINE       0     0     0
\tcache
\t  /dev/nvme1n1p1                                     ONLINE       0     0     0
\tspares
\t  /dev/sde                                           AVAIL
"""
    adapter = GenericLinuxStorageAdapter()
    with patch.object(adapter, "_run_cmd", return_value=(0, sample_zstat, "")):
        members = adapter._parse_zpool_members("tank")

    assert len(members) == 6

    # Verify members
    raidz_members = [m for m in members if m.type == "RAIDZ Member"]
    assert len(raidz_members) == 3
    assert raidz_members[0].role == "parity"
    assert raidz_members[2].num_reads == 1
    assert raidz_members[2].num_errors == 2

    log_m = next(m for m in members if m.role == "log")
    assert log_m.type == "Log (SLOG)"

    cache_m = next(m for m in members if m.role == "cache")
    assert cache_m.type == "Cache"

    spare_m = next(m for m in members if m.role == "spare")
    assert spare_m.status == "AVAIL"


def test_btrfs_df_chunk_parsing():
    """Verifies btrfs filesystem df output parses exact chunk RAID profiles."""
    sample_df = """
Data, RAID1: total=1.00TiB, used=500.00GiB
System, RAID1: total=32.00MiB, used=16.00KiB
Metadata, RAID1: total=2.00GiB, used=512.00MiB
GlobalReserve, single: total=512.00MiB, used=0.00B
"""
    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")

    def mock_run_cmd(cmd):
        if "df" in cmd:
            return 0, sample_df, ""
        return 0, "", ""

    with patch.object(adapter, "_run_cmd", side_effect=mock_run_cmd), patch("shutil.disk_usage") as mock_usage:
        mock_usage.return_value = MagicMock(total=1000000000, used=500000000, free=500000000)
        with patch.object(DiskDiscoveryHAL, "discover_physical_disks", return_value=[]):
            pools = adapter.list_pools()

    assert len(pools) >= 1
    assert pools[0].fs_profile == "raid1"
    assert pools[0].parity_protected is True


def test_truenas_and_proxmox_observer_mode():
    """Verifies TrueNAS and Proxmox adapters operate in observer mode with disarmed mutations."""
    truenas_adapter = TrueNASStorageAdapter()
    assert truenas_adapter.get_platform_type() == PlatformType.TRUENAS
    caps = truenas_adapter.get_capabilities()
    assert caps.is_observer_mode is True
    assert caps.can_create_pools is False
    assert caps.can_destroy_pools is False
    assert caps.can_manage_shares is False
    assert caps.can_trigger_scrub is True

    with pytest.raises(PlatformCapabilityError):
        truenas_adapter.create_pool("new_pool", ["/dev/sdb"])

    with pytest.raises(PlatformCapabilityError):
        truenas_adapter.destroy_pool("pool1")

    pve_adapter = ProxmoxStorageAdapter()
    assert pve_adapter.get_platform_type() == PlatformType.PROXMOX
    pve_caps = pve_adapter.get_capabilities()
    assert pve_caps.is_observer_mode is True
    assert pve_caps.can_create_pools is False

    with pytest.raises(PlatformCapabilityError):
        pve_adapter.create_pool("pve_pool", ["/dev/sdc"])

    # Test detection routing in get_storage_platform
    with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.TRUENAS):
        assert isinstance(get_storage_platform(force_refresh=True), TrueNASStorageAdapter)

    with patch.object(StoragePlatformDetector, "detect", return_value=PlatformType.PROXMOX):
        assert isinstance(get_storage_platform(force_refresh=True), ProxmoxStorageAdapter)


def test_pal_is_storage_busy_interlock():
    """Verifies is_storage_busy detects active Btrfs scrubs, balances, and ZFS scrubs."""
    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")

    # 1. Btrfs scrub active
    with patch.object(adapter, "_run_cmd", return_value=(0, "scrub running: 20% done", "")):
        assert adapter.is_storage_busy() is True

    # 2. Btrfs balance active
    def mock_cmd_balance(cmd):
        if "balance" in cmd:
            return 0, "Balance on /mnt/storage is running", ""
        return 0, "scrub idle", ""

    with patch.object(adapter, "_run_cmd", side_effect=mock_cmd_balance):
        assert adapter.is_storage_busy() is True

    # 3. ZFS scrub active
    def mock_cmd_zfs(cmd):
        if "zpool" in cmd and "status" in cmd:
            return 0, "pool: tank\nscan: scrub in progress since Sun Oct 11", ""
        return 0, "scrub idle", ""

    with patch.object(adapter, "_run_cmd", side_effect=mock_cmd_zfs):
        assert adapter.is_storage_busy() is True

    # 4. Storage completely idle
    with patch.object(adapter, "_run_cmd", return_value=(0, "no scrub running", "")):
        assert adapter.is_storage_busy() is False


def test_led_speed_and_port_search():
    """Verifies send_led_packet does not double-invert speed and find_led_port checks ttyUSB."""
    with (
        patch("backend.hardware.led.find_led_port", return_value="/dev/ttyUSB0"),
        patch("backend.hardware.led._get_serial_connection") as mock_conn,
        patch("os.path.exists", side_effect=lambda p: p in ("/dev/ttyUSB0",)),
    ):
        mock_handle = MagicMock()
        mock_conn.return_value = mock_handle

        success, msg = send_led_packet(mode=1, r1=255, g1=100, b1=50, speed=12)
        assert success is True
        assert mock_handle.write.called
        written_frame = mock_handle.write.call_args[0][0]
        # Frame format: [0xFF, 0xFF, mode, r1, g1, b1, r2, g2, b2, speed, crc]
        # Speed payload byte should be directly 12 (not (-12)&0xFF)
        assert written_frame[9] == 12

    # Port search path includes ttyUSB
    with patch("backend.hardware.fans.is_zettlab_appliance", return_value=True):
        with patch("os.path.exists", side_effect=lambda p: p == "/dev/ttyUSB0"):
            found = find_led_port()
            assert found == "/dev/ttyUSB0"


def test_lcd_16bpp_framebuffer_support():
    """Verifies discover_fb_geometry detects 16bpp and returns width, height, stride, and bpp."""

    def mock_file_open(path, *args, **kwargs):
        content = ""
        p_str = str(path)
        if "stride" in p_str:
            content = "704\n"
        elif "bits_per_pixel" in p_str:
            content = "16\n"
        elif "virtual_size" in p_str:
            content = "172,640\n"
        m = MagicMock()
        m.read.return_value = content
        m.__enter__.return_value = m
        return m

    with (
        patch("os.path.exists", return_value=True),
        patch("builtins.open", side_effect=mock_file_open),
    ):
        w, h, stride = discover_fb_geometry()
        bpp = discover_fb_bpp()
        assert w == 172
        assert h == 640
        assert stride == 704
        assert bpp == 16


def test_ups_watchdog_preserves_orchestrator():
    """Verifies graceful_docker_teardown does not kill zettnas-toolkit containers."""
    mock_containers = [
        {"id": "c1", "name": "plex", "state": "running"},
        {"id": "c2", "name": "zettnas-toolkit", "state": "running"},
        {"id": "c3", "name": "zettnas-samba", "state": "running"},
        {"id": "c4", "name": "vaultwarden", "state": "running"},
    ]

    stopped = []

    def mock_action(cid, action):
        stopped.append((cid, action))

    with (
        patch("backend.hardware.docker_stats.read_docker_containers", return_value=mock_containers),
        patch("backend.hardware.docker_stats.container_action", side_effect=mock_action),
    ):
        graceful_docker_teardown()

    stopped_ids = [cid for cid, act in stopped]
    assert "c1" in stopped_ids
    assert "c4" in stopped_ids
    assert "c2" not in stopped_ids
    assert "c3" not in stopped_ids
