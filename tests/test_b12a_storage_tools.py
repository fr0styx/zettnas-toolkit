"""B12a (REL-4, D2): btrfs and mdadm in every image, Debian's ZFS 2.4 in the full image; ZFS
commands only when the image's tools match the host's ZFS module and /dev/zfs is there."""

import os
import re

import pytest

from backend.hardware.pal import base

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize(
    ("host", "image", "dev", "why"),
    [
        ("2.4.4-1", "", True, "no ZFS tools"),
        ("", "2.4.4-1~bpo13+1", True, "no ZFS module"),
        ("2.4.4-1", "2.4.4-1~bpo13+1", False, "/dev/zfs is not passed"),
        ("2.2.7-1", "2.4.4-1~bpo13+1", True, "do not match"),
        ("2.4.1-1", "2.4.4-1~bpo13+1", True, ""),  # same 2.4: fine
    ],
)
def test_zfs_is_used_only_when_it_matches_the_host(host, image, dev, why):
    got = base.zfs_problem(host=host, image=image, dev_zfs=dev)
    assert (why in got) if why else got == ""


def test_versions_are_compared_by_major_and_minor():
    assert base._major_minor("zfs-2.4.4-1") == (2, 4)
    assert base._major_minor("2.3.9-0+deb13u1") == (2, 3)
    assert base._major_minor("unknown") is None


@pytest.mark.real_storage_tools
def test_a_mismatch_turns_zfs_off_and_says_why(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(base, "_ZFS_PROBLEM", {})
    monkeypatch.setattr(
        base, "zfs_problem", lambda: "the ZFS tools in this image (2.4.4) do not match the host's ZFS (2.2.7)"
    )
    tools = base.storage_tools()
    assert tools == {"btrfs": True, "zfs": False, "zpool": False, "mdadm": True}
    assert "do not match" in base.storage_tools_problem()


@pytest.mark.real_storage_tools
def test_a_match_keeps_zfs(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/sbin/{name}")
    monkeypatch.setattr(base, "_ZFS_PROBLEM", {})
    monkeypatch.setattr(base, "zfs_problem", lambda: "")
    assert base.storage_tools()["zfs"] is True and base.storage_tools_problem() == ""


def test_snapshots_say_why_zfs_is_not_used(monkeypatch):
    from backend.services import snapshot_service

    class Caps:
        can_snapshot = False

    class Pal:
        def get_capabilities(self):
            return Caps()

    monkeypatch.setattr(base, "_ZFS_PROBLEM", {"reason": "the host's /dev/zfs is not passed to the container"})
    ok, why = snapshot_service.availability(Pal())
    assert ok is False and "/dev/zfs is not passed" in why


def test_the_image_carries_the_tools_the_way_d2_decided():
    with open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8") as f:
        text = f.read()
    core = text.split("# Core:", 1)[1].split("rm -rf /var/lib/apt/lists/*", 1)[0]
    assert "btrfs-progs" in core and "mdadm" in core  # every image
    zfs = re.search(r'RUN if \[ "\$VARIANT" = "full" \]; then \\\n    printf.*?fi', text, re.S)
    assert zfs and "trixie-backports" in zfs.group(0) and "zfsutils-linux" in zfs.group(0)  # full image only
    assert "zfsutils-linux" not in core
    assert "ENV ZFS_MODULE_TIMEOUT=0" in text  # no 10 s wait per call without /dev/zfs
