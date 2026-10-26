"""The platform detector and the generic Linux disk-path resolver (backend/hardware/pal)."""

import os

import pytest

from backend.hardware.pal import base as pal_base
from backend.hardware.pal.base import PlatformType
from backend.hardware.pal.detect import StoragePlatformDetector
from backend.hardware.pal.generic_linux import GenericLinuxStorageAdapter


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for var in ("ZETTNAS_PLATFORM", "ZETTNAS_OBSERVER_ADAPTER", "ZETTNAS_PAL_MODE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(pal_base, "_find_emhttp_dir", lambda: None)
    proc = tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    monkeypatch.setattr(pal_base, "HOST_PROC", str(proc))
    return proc


@pytest.mark.parametrize(
    "value, expected",
    [
        ("unraid", PlatformType.UNRAID),
        ("scale", PlatformType.TRUENAS),
        ("pve", PlatformType.PROXMOX),
        ("fydeos", PlatformType.FYGOOS),
        ("zettlab", PlatformType.ZETTOS),
        ("ugreen", PlatformType.UGOS),
        ("readonly", PlatformType.GENERIC_OBSERVER),
        ("linux", PlatformType.GENERIC_LINUX),
    ],
)
def test_the_platform_can_be_set_by_environment(clean_env, monkeypatch, value, expected):
    monkeypatch.setenv("ZETTNAS_PLATFORM", value)
    assert StoragePlatformDetector.detect() == expected


def test_auto_and_observer_settings(clean_env, monkeypatch):
    monkeypatch.setenv("ZETTNAS_OBSERVER_ADAPTER", "truenas")
    assert StoragePlatformDetector.detect() == PlatformType.TRUENAS
    monkeypatch.setenv("ZETTNAS_OBSERVER_ADAPTER", "auto")
    monkeypatch.setenv("ZETTNAS_PAL_MODE", "proxmox")
    assert StoragePlatformDetector.detect() == PlatformType.PROXMOX


def test_unraid_is_found_by_its_state_folder(clean_env, monkeypatch):
    monkeypatch.setattr(pal_base, "_find_emhttp_dir", lambda: "/var/local/emhttp")
    assert StoragePlatformDetector.detect() == PlatformType.UNRAID


@pytest.mark.parametrize(
    "where, text",
    [
        ("1/mounts", "overlay / overlay rw,upperdir=/zettlab/upper 0 0\n"),
        ("mounts", "/dev/mmcblk0p2 /zettos ext4 rw 0 0\n"),
        ("cmdline", "BOOT_IMAGE=/boot/vmlinuz root=/dev/mmcblk0p2 zettos.mode=nas\n"),
    ],
)
def test_zettos_is_found_in_mounts_or_the_kernel_command_line(clean_env, where, text):
    (clean_env / where).write_text(text)
    assert StoragePlatformDetector.detect() == PlatformType.ZETTOS


@pytest.fixture
def host_dev(tmp_path, monkeypatch):
    dev = tmp_path / "dev"
    by_id = dev / "disk" / "by-id"
    by_id.mkdir(parents=True)
    (dev / "sdzq").write_text("")
    for name in ("usb-Ext_Drive_1", "wwn-0x5000c500a1b2c3d4", "ata-WDC_WD40_XYZ", "ata-WDC_WD40_XYZ-part1"):
        os.symlink("../../sdzq", by_id / name)
    (dev / "sdzr").write_text("")
    monkeypatch.setattr(pal_base, "HOST_DEV", str(dev))
    return dev


def test_disks_resolve_to_the_most_stable_by_id_name(host_dev):
    a = GenericLinuxStorageAdapter(pool_path="/tmp/zn-pool")
    assert a._resolve_disk_path("sdzq") == str(host_dev / "disk" / "by-id" / "wwn-0x5000c500a1b2c3d4")
    assert a._resolve_disk_path("/dev/sdzq").endswith("wwn-0x5000c500a1b2c3d4")


def test_disks_without_by_id_names_fall_back_to_the_node(host_dev):
    a = GenericLinuxStorageAdapter(pool_path="/tmp/zn-pool")
    assert a._resolve_disk_path("sdzr") == str(host_dev / "sdzr")
    assert a._resolve_disk_path("/dev/sdzr") == "/dev/sdzr"  # absolute, not under the host /dev: kept
    assert a._resolve_disk_path("sdzx") == "/dev/sdzx"  # unknown: the conventional node


def test_by_id_paths_are_kept_or_mapped_to_the_host(host_dev):
    a = GenericLinuxStorageAdapter(pool_path="/tmp/zn-pool")
    on_host = "/disk/by-id/ata-WDC_WD40_XYZ"
    assert a._resolve_disk_path(on_host) == str(host_dev / "disk" / "by-id" / "ata-WDC_WD40_XYZ")
    assert a._resolve_disk_path("/dev/disk/by-id/missing-disk") == "/dev/disk/by-id/missing-disk"


def test_commands_report_failures_as_codes(monkeypatch):
    import subprocess

    a = GenericLinuxStorageAdapter(pool_path="/tmp/zn-pool")
    monkeypatch.setattr(subprocess, "run", lambda *x, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert a._run_cmd(["zfs", "list"]) == (1, "", "boom")


@pytest.mark.parametrize(
    "version, expected",
    [
        ("Linux version 6.1.106-Unraid", PlatformType.UNRAID),
        ("Linux version 5.15 (fydeos build)", PlatformType.FYGOOS),
        ("Linux version 6.6 ugreen-nas", PlatformType.UGOS),
        ("Linux version 6.8.12-4-pve", PlatformType.PROXMOX),
        ("Linux version 6.6.44-production+truenas", PlatformType.TRUENAS),
    ],
)
def test_the_kernel_version_names_the_platform(clean_env, version, expected):
    (clean_env / "version").write_text(version)
    assert StoragePlatformDetector.detect() == expected


@pytest.mark.parametrize(
    "marker, expected",
    [
        ("/etc/fyde-release", PlatformType.FYGOOS),
        ("/etc/ugreen", PlatformType.UGOS),
        ("/etc/synoinfo.conf", PlatformType.GENERIC_OBSERVER),
    ],
)
def test_appliance_os_marker_files(clean_env, monkeypatch, marker, expected):
    real_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda p: p == marker or real_exists(p))
    assert StoragePlatformDetector.detect() == expected


def test_unraid_shares_come_from_the_state_files(tmp_path, monkeypatch):
    from backend.hardware.pal.unraid import UnraidStorageAdapter

    em = tmp_path / "emhttp"
    em.mkdir()
    (em / "shares.ini").write_text(
        '["media"]\nname="media"\ncomment="Films"\nuseCache="yes"\ncachePool="cache"\n'
        '["backups"]\nname="backups"\ncomment=""\nuseCache="no"\n'
    )
    (em / "sec.ini").write_text(
        '["media"]\nexport="e"\nsecurity="public"\n["backups"]\nexport="-"\nsecurity="private"\n'
    )
    (em / "sec_nfs.ini").write_text('["media"]\nexport="e"\n["backups"]\nexport="-"\n')
    monkeypatch.setattr(pal_base, "_find_emhttp_dir", lambda: str(em))
    adapter = UnraidStorageAdapter()
    adapter._emhttp_dir = str(em)
    shares = {s.name: s for s in adapter.list_shares()}
    assert set(shares) == {"media", "backups"}
    assert shares["media"].comment == "Films"


@pytest.mark.parametrize(
    "line, expected",
    [
        ("overlay {p} overlay rw,lowerdir=/rom,upperdir=/zettlab/up 0 0", True),
        ("/dev/mmcblk0p3 {p} ext4 rw 0 0", True),
        ("/dev/sdb1 {p} ext4 rw 0 0", False),
    ],
)
def test_the_os_overlay_and_emmc_are_recognised(tmp_path, monkeypatch, line, expected):
    from backend.hardware.pal.base import StoragePlatformAdapter

    target = tmp_path / "vol"
    target.mkdir()
    proc = tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    (proc / "1" / "mounts").write_text(line.format(p=target) + "\n")
    monkeypatch.setattr(pal_base, "HOST_PROC", str(proc))
    assert StoragePlatformAdapter._is_os_overlay_or_emmc(str(target)) is expected
    assert StoragePlatformAdapter._is_os_overlay_or_emmc(str(tmp_path / "missing")) is False


@pytest.mark.parametrize("total_gb, expected", [(64, True), (4000, False)])
def test_a_folder_on_a_small_emmc_root_counts_as_the_os(tmp_path, monkeypatch, total_gb, expected):
    import shutil
    import types

    from backend.hardware.pal.base import StoragePlatformAdapter

    target = tmp_path / "data"
    target.mkdir()
    proc = tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    (proc / "1" / "mounts").write_text("/dev/mmcblk0p2 / ext4 rw 0 0\n")
    monkeypatch.setattr(pal_base, "HOST_PROC", str(proc))
    real_stat = os.stat
    same = types.SimpleNamespace(st_dev=7)
    monkeypatch.setattr(os, "stat", lambda p, *a, **k: same if p in (str(target), "/") else real_stat(p, *a, **k))
    monkeypatch.setattr(shutil, "disk_usage", lambda p: types.SimpleNamespace(total=total_gb * 1024**3, used=0, free=0))
    assert StoragePlatformAdapter._is_os_overlay_or_emmc(str(target)) is expected
