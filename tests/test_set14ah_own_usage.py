"""B35 addition: a shared folder's own size where ZFS or Btrfs keep it, read from metadata only."""

from unittest.mock import patch

from backend.hardware.pal import generic_linux as gl


def _run(answers):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return answers.get(cmd[0], (1, "", "no"))

    return run, calls


def test_a_zfs_dataset_gives_used_and_quota():
    run, calls = _run({"zfs": (0, "1073741824\n5368709120", "")})
    with (
        patch("backend.hardware.pal.base.storage_tools", return_value={"zfs": True, "btrfs": False}),
        patch.object(gl, "zfs_dataset_at", return_value="tank/photos"),
    ):
        assert gl.own_usage("/mnt/tank/photos", run) == (1073741824, 5368709120)
    assert calls == [["zfs", "get", "-Hp", "-o", "value", "used,quota", "tank/photos"]]


def test_a_btrfs_subvolume_with_quotas():
    out = "qgroupid         rfer         excl     max_rfer \n--------         ----         ----     -------- \n0/257       123456789     12345678         none \n"
    run, _ = _run({"btrfs": (0, out, "")})
    with (
        patch("backend.hardware.pal.base.storage_tools", return_value={"zfs": False, "btrfs": True}),
        patch.object(gl, "is_subvolume", return_value=True),
    ):
        assert gl.own_usage("/mnt/pool/media", run) == (123456789, 0)


def test_btrfs_without_quotas_or_a_plain_folder_has_none():
    run, _ = _run({"btrfs": (1, "", "ERROR: can't list qgroups: quotas not enabled")})
    with (
        patch("backend.hardware.pal.base.storage_tools", return_value={"zfs": False, "btrfs": True}),
        patch.object(gl, "is_subvolume", return_value=True),
    ):
        assert gl.own_usage("/mnt/pool/media", run) is None
    with (
        patch("backend.hardware.pal.base.storage_tools", return_value={"zfs": True, "btrfs": True}),
        patch.object(gl, "zfs_dataset_at", return_value=""),
        patch.object(gl, "is_subvolume", return_value=False),
    ):
        assert gl.own_usage("/mnt/pool/plain", run) is None


def test_the_card_figures(tmp_path):
    adapter = gl.GenericLinuxStorageAdapter.__new__(gl.GenericLinuxStorageAdapter)
    adapter._pool_path = str(tmp_path)
    with patch.object(gl, "own_usage", return_value=(2_000, 10_000)):
        fig = adapter._share_figures(str(tmp_path))
    assert fig["usage_is_own"] is True
    assert (fig["used_bytes"], fig["free_bytes"], fig["total_bytes"], fig["used_pct"]) == (2_000, 8_000, 10_000, 20.0)
    with patch.object(gl, "own_usage", return_value=None):
        fig = adapter._share_figures(str(tmp_path))
    assert fig["usage_is_own"] is False
