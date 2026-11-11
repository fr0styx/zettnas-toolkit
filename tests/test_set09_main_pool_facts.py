"""SET-09: the main pool's facts are measured, not invented, and listing pools looks at no drive."""

import pytest

from backend.hardware.pal_storage import GenericLinuxStorageAdapter

DF_RAID1 = "Data, RAID1: total=1.00GiB, used=512.00MiB\nMetadata, RAID1: total=1.00GiB, used=1.00MiB\n"


@pytest.fixture
def nas():
    adapter = GenericLinuxStorageAdapter(pool_path="/mnt/storage")
    state = {"ran": [], "fs": "btrfs", "df": (0, DF_RAID1, "")}
    adapter._parse_mounts = lambda: [{"target": "/mnt/storage", "fstype": state["fs"]}] if state["fs"] else []

    def run(cmd):
        state["ran"].append(cmd)
        return state["df"] if cmd[:3] == ["btrfs", "filesystem", "df"] else (1, "", "not run in this test")

    adapter._run_cmd = run
    return adapter, state


def test_a_btrfs_pool_names_the_level_btrfs_reports(nas):
    adapter, state = nas
    assert adapter._main_pool_facts() == ("btrfs", "raid1")
    state["df"] = (0, "Data, single: total=1.00GiB, used=1.00MiB\n", "")
    assert adapter._main_pool_facts() == ("btrfs", "single")


def test_no_level_is_guessed_when_btrfs_gives_no_answer(nas):
    adapter, state = nas
    state["df"] = (1, "", "not a btrfs filesystem")
    assert adapter._main_pool_facts() == ("btrfs", "")  # it said "raid1" for any NAS with two drives
    state["fs"] = ""  # the mount table does not say
    assert adapter._main_pool_facts() == ("unknown", "")


@pytest.mark.parametrize("fs", ["ext4", "xfs", "zfs", "overlay"])
def test_another_file_system_is_named_and_no_btrfs_command_looks_at_the_drives(nas, fs):
    adapter, state = nas
    state["fs"] = fs
    assert adapter._main_pool_facts() == (fs, "")
    assert state["ran"] == []


def test_listing_pools_never_runs_the_command_that_scans_every_drive(nas, monkeypatch):
    adapter, state = nas
    state["df"] = (1, "", "")
    monkeypatch.setattr(adapter, "_is_os_overlay_or_emmc", lambda path: False)
    monkeypatch.setattr(adapter, "_discover_hal_disks", lambda: [])
    monkeypatch.setattr(adapter, "_parse_mdstat", lambda: {})
    pools = adapter.list_pools()
    assert not [c for c in state["ran"] if c[:3] == ["btrfs", "filesystem", "show"]], state["ran"]
    main = next(p for p in pools if p.id == "default_pool")
    assert main.fs_profile == "" and main.parity_protected is False and main.pool_type == "single"
