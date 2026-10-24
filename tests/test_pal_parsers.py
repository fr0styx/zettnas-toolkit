"""Storage platform layer: shared parsers (mdstat, mounts, INI, smb.conf, zpool status), usage
discovery, OS-disk detection and the ZFS observer adapters (TrueNAS, Proxmox)."""

import json
import subprocess

import pytest

from backend.hardware import pal_storage as pal


class Cmd:
    """A fake _run_cmd answering by command prefix."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(cmd)
        line = " ".join(cmd)
        for prefix, answer in self.answers.items():
            if line.startswith(prefix):
                return answer
        return 1, "", "not faked"


@pytest.fixture
def adapter(monkeypatch):
    a = pal.GenericLinuxStorageAdapter()
    a._run_cmd = Cmd()
    return a


@pytest.fixture
def proc(tmp_path, monkeypatch):
    root = tmp_path / "proc"
    root.mkdir()
    monkeypatch.setattr(pal, "HOST_PROC", str(root))
    monkeypatch.setattr(pal, "HOST_SYS", str(tmp_path / "sys"))
    return root


class TestRunCmd:
    def test_errors_become_codes(self, monkeypatch):
        a = pal.GenericLinuxStorageAdapter()

        def missing(*a, **k):
            raise FileNotFoundError("zpool")

        monkeypatch.setattr(pal.subprocess, "run", missing)
        assert a._run_cmd(["zpool", "list"]) == (127, "", "Command not found: zpool")

        def slow(*a, **k):
            raise subprocess.TimeoutExpired("zpool", 60)

        monkeypatch.setattr(pal.subprocess, "run", slow)
        assert a._run_cmd(["zpool"])[0] == 124


MDSTAT = """Personalities : [raid1] [raid5]
md0 : active raid1 sdb1[1] sda1[0]
      976630464 blocks super 1.2 [2/2] [UU]
md1 : active raid5 sde[2] sdd[1] sdc[0]
      1953260544 blocks super 1.2 level 5, 512k chunk [3/2] [UU_]
      [====>................]  recovery = 22.4% (219000000/976630272) finish=80.1min
md2 : active raid1 sdf[0] sdg[1]
unused devices: <none>
"""


class TestParsers:
    def test_mdstat(self, adapter, proc, tmp_path):
        (proc / "mdstat").write_text(MDSTAT)
        (tmp_path / "sys" / "block" / "md2").mkdir(parents=True)
        (tmp_path / "sys" / "block" / "md2" / "size").write_text("2048")
        md = adapter._parse_mdstat()
        assert md["md0"]["level"] == "raid1" and md["md0"]["members"] == ["sdb1", "sda1"] and not md["md0"]["degraded"]
        assert md["md0"]["size_bytes"] == 976630464 * 1024
        assert md["md1"]["degraded"] and md["md1"]["sync_action"] == "recovery" and md["md1"]["progress_pct"] == 22.4
        assert md["md2"]["size_bytes"] == 2048 * 512

    def test_mounts_skip_pseudo_filesystems(self, adapter, proc):
        (proc / "1").mkdir()
        (proc / "1" / "mounts").write_text(
            "proc /proc proc rw 0 0\n/dev/sdb1 /mnt/disk1 xfs rw,noatime 0 0\noverlay / overlay rw 0 0\n"
            "tmpfs /run tmpfs rw 0 0\n/dev/md0 /mnt/pool btrfs rw 0 0\n/dev/sdb1 /mnt/disk1 xfs rw 0 0\n"
        )
        mounts = [m for m in adapter._parse_mounts() if m["mountpoint"].startswith("/mnt/")]
        assert [(m["device"], m["mountpoint"], m["fstype"]) for m in mounts] == [
            ("/dev/sdb1", "/mnt/disk1", "xfs"),
            ("/dev/md0", "/mnt/pool", "btrfs"),
        ]

    def test_ini_sections(self, tmp_path):
        f = tmp_path / "disks.ini"
        f.write_text('; comment\n["disk1"]\nname="disk1"\nstatus="DISK_OK"\n[parity]\nsize=12000\nbroken line\n')
        assert pal._parse_ini_sections(str(f)) == {
            "disk1": {"name": "disk1", "status": "DISK_OK"},
            "parity": {"size": "12000"},
        }
        assert pal._parse_ini_sections(str(tmp_path / "none.ini")) == {}

    def test_smb_conf_shares(self, tmp_path, monkeypatch):
        media = tmp_path / "media"
        media.mkdir()
        conf = tmp_path / "smb.conf"
        conf.write_text(
            f"[global]\nworkgroup = WG\n[homes]\npath=/home\n[Media]\npath = {media}\ncomment = Films\nguest ok = yes\n"
            "[Private]\npath = /nonexistent/private\n[NoPath]\ncomment = x\n"
        )
        monkeypatch.setattr(pal, "SMB_CONF_PATHS", (str(conf),))
        shares = {s.name: s for s in pal.TrueNASStorageAdapter()._parse_smb_conf()}
        assert set(shares) == {"Media", "Private"}
        assert (
            shares["Media"].security == "public"
            and shares["Media"].comment == "Films"
            and shares["Media"].total_bytes > 0
        )
        assert shares["Private"].security == "private"

    def test_no_smb_conf(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pal, "SMB_CONF_PATHS", (str(tmp_path / "none.conf"),))
        assert pal.TrueNASStorageAdapter()._parse_smb_conf() == []


ZPOOL_STATUS = """  pool: tank
 state: DEGRADED
config:

    NAME                        STATE     READ WRITE CKSUM
    tank                        DEGRADED     0     0     0
      raidz1-0                  DEGRADED     0     0     0
        /dev/sda1               ONLINE       0     0     0
        /dev/sdb1               FAULTED      3     1     7
      mirror-1                  ONLINE       0     0     0
        /dev/sdc                ONLINE       0     0     0
    logs
      /dev/nvme0n1p1            ONLINE       0     0     0
    cache
      /dev/nvme1n1              ONLINE       0     0     0
    spares
      /dev/sdd                  AVAIL
    special
      /dev/nvme2n1              ONLINE       0     0     0

errors: No known data errors
"""


class TestZpoolMembers:
    def test_roles_and_states(self, adapter):
        adapter._run_cmd.answers["zpool status -P tank"] = (0, ZPOOL_STATUS, "")
        members = {m.name: m for m in adapter._parse_zpool_members("tank")}
        assert members["sda"].type == "RAIDZ Member" and members["sda"].role == "parity"
        assert members["sdb"].status == "FAULTED" and members["sdb"].num_errors == 7 and members["sdb"].num_reads == 3
        assert members["sdc"].type == "Mirror Member"
        assert members["nvme0n1"].role == "log" and not members["nvme0n1"].rotational
        assert members["nvme1n1"].role == "cache" and members["sdd"].role == "spare"
        assert members["nvme2n1"].role == "metadata"

    def test_no_pool(self, adapter):
        assert adapter._parse_zpool_members("none") == []


class TestUsage:
    def test_from_the_mountpoint(self, adapter, tmp_path, monkeypatch):
        monkeypatch.setattr(adapter, "_resolve_container_accessible_path", lambda p: str(tmp_path))
        monkeypatch.setattr(adapter, "_is_os_overlay_or_emmc", lambda p: False)
        tot, usd, fre, pct, fstype = adapter._get_mount_or_device_usage("/mnt/pool")
        assert tot > 0 and fstype is None and 0 <= pct <= 100

    def test_from_lsblk(self, adapter, tmp_path, monkeypatch):
        dev = tmp_path / "md3"
        dev.write_text("")
        monkeypatch.setattr(
            pal.os.path, "join", lambda *p: str(dev) if p[-1] == "md3" and p[0] in ("/dev",) else "/".join(p)
        )
        monkeypatch.setattr(adapter, "_parse_fs_superblock", lambda node: None)
        monkeypatch.setattr(adapter, "_read_casaos_storage_db", lambda: {})
        adapter._run_cmd.answers["lsblk"] = (
            0,
            json.dumps({"blockdevices": [{"fstype": "ext4", "fssize": "1000", "fsused": "250", "fsavail": "700"}]}),
            "",
        )
        assert adapter._get_mount_or_device_usage(None, "md3") == (1000, 250, 700, 25.0, "ext4")

    def test_from_the_casaos_database(self, adapter, monkeypatch):
        monkeypatch.setattr(
            adapter, "_read_casaos_storage_db", lambda: {"sdz": {"size": 2000, "used": 500, "fs_type": "btrfs"}}
        )
        assert adapter._get_mount_or_device_usage(None, "sdz") == (2000, 500, 1500, 25.0, "btrfs")

    def test_fallback(self, adapter, monkeypatch):
        monkeypatch.setattr(adapter, "_read_casaos_storage_db", lambda: {})
        assert adapter._get_mount_or_device_usage(None, "sdq", fallback_total=42) == (42, 0, 42, 0.0, None)


class TestOsDisk:
    def test_overlay_mount_is_the_os(self, proc, tmp_path):
        target = tmp_path / "rootfs"
        target.mkdir()
        (proc / "1").mkdir()
        (proc / "1" / "mounts").write_text(f"overlay {target} overlay rw,lowerdir=/rom,upperdir=/zettlab/up 0 0\n")
        assert pal.StoragePlatformAdapter._is_os_overlay_or_emmc(str(target))

    def test_emmc_mount_is_the_os(self, proc, tmp_path):
        target = tmp_path / "boot"
        target.mkdir()
        (proc / "1").mkdir()
        (proc / "1" / "mounts").write_text(f"/dev/mmcblk0p1 {target} ext4 rw 0 0\n")
        assert pal.StoragePlatformAdapter._is_os_overlay_or_emmc(str(target))

    def test_data_disk_is_not(self, proc, tmp_path):
        (proc / "1").mkdir()
        (proc / "1" / "mounts").write_text(f"/dev/sdb1 {tmp_path} xfs rw 0 0\n")
        assert not pal.StoragePlatformAdapter._is_os_overlay_or_emmc(str(tmp_path))
        assert not pal.StoragePlatformAdapter._is_os_overlay_or_emmc("/nonexistent/path")


@pytest.mark.parametrize(
    "cls, platform", [(pal.TrueNASStorageAdapter, "truenas"), (pal.ProxmoxStorageAdapter, "proxmox")]
)
class TestZfsObservers:
    def make(self, cls, monkeypatch, answers):
        a = cls()
        a._run_cmd = Cmd(answers)
        monkeypatch.setattr(a, "_discover_hal_disks", lambda: [])
        return a

    def test_pools_from_zpool_list(self, cls, platform, monkeypatch):
        a = self.make(
            cls, monkeypatch, {"zpool list": (0, "tank\t1000\t400\t600\tONLINE\nbackup\t500\t50\t450\tDEGRADED\n", "")}
        )
        pools = {p.id: p for p in a.list_pools()}
        assert pools["tank"].used_pct == 40.0 and pools["tank"].status == "HEALTHY"
        assert pools["backup"].status == "DEGRADED"

    def test_fallback_pool_without_zfs(self, cls, platform, monkeypatch):
        pools = self.make(cls, monkeypatch, {}).list_pools()
        assert len(pools) >= 1  # TrueNAS: its boot pool; Proxmox: its directory storage
        if platform == "truenas":
            assert pools[0].fs_type == "zfs"

    def test_scrub(self, cls, platform, monkeypatch):
        a = self.make(
            cls,
            monkeypatch,
            {
                "zpool scrub -s tank": (0, "", ""),
                "zpool scrub tank": (0, "", ""),
                "zpool status tank": (0, "scan: scrub in progress since Sat", ""),
            },
        )
        assert a.trigger_scrub("tank")["status"] == "started"
        assert a.trigger_scrub("tank", "cancel")["status"] == "cancelled"
        assert a.trigger_scrub("tank", "status")["status"] == "active"
        assert a.trigger_scrub("tank")["platform"] == platform

    def test_busy_while_scrubbing(self, cls, platform, monkeypatch):
        a = self.make(cls, monkeypatch, {"zpool status": (0, "  scan: resilver in progress since ...", "")})
        assert a.is_storage_busy()
        a._run_cmd.answers["zpool status"] = (0, "scan: scrub repaired 0B", "")
        assert not a.is_storage_busy()

    def test_observers_refuse_pool_changes(self, cls, platform, monkeypatch):
        a = self.make(cls, monkeypatch, {})
        assert a.get_capabilities().is_observer_mode
        with pytest.raises(pal.PlatformCapabilityError):
            a.create_pool("x")
        with pytest.raises(pal.PlatformCapabilityError):
            a.destroy_pool("x")


@pytest.mark.parametrize(
    "name, disk",
    [
        ("sdb1", "sdb"),
        ("sdb", "sdb"),
        ("nvme0n1p1", "nvme0n1"),
        ("nvme1n1", "nvme1n1"),
        ("mmcblk0p2", "mmcblk0"),
        ("vda3", "vda"),
        ("dm-0", "dm-0"),
    ],
)
def test_whole_disk(name, disk):
    """Regression: whole NVMe disks were renamed (nvme1n1 -> nvme1n) and matched nothing."""
    assert pal._whole_disk(name) == disk
