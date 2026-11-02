"""NREL-5: on a btrfs pool a new share is a subvolume, so snapshots and quotas work on it."""

from backend.hardware.pal import generic_linux as gl


def test_fs_of_takes_the_longest_mount(tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_text(
        "/dev/sda1 / ext4 rw 0 0\n"
        f"/dev/sdb1 {tmp_path}/pool btrfs rw 0 0\n"
        f"/dev/sdc1 {tmp_path}/pool/fast\\040disk xfs rw 0 0\n"
        "junk\n"
    )
    (tmp_path / "pool" / "photos").mkdir(parents=True)
    (tmp_path / "pool" / "fast disk").mkdir()
    assert gl.fs_of(str(tmp_path / "pool" / "photos"), str(mounts)) == "btrfs"
    assert gl.fs_of(str(tmp_path / "pool" / "fast disk"), str(mounts)) == "xfs"
    assert gl.fs_of("/somewhere/else", str(mounts)) == "ext4"
    assert gl.fs_of("/x", str(tmp_path / "missing")) == ""


def _adapter(tmp_path, monkeypatch, fs, code=0):
    a = gl.GenericLinuxStorageAdapter(str(tmp_path))
    calls = []

    def run(cmd):
        calls.append(cmd)
        if code == 0:
            (tmp_path / cmd[-1].rsplit("/", 1)[-1]).mkdir()
        return code, "", "not allowed" if code else ""

    monkeypatch.setattr(a, "_run_cmd", run)
    monkeypatch.setattr(gl, "fs_of", lambda path: fs)
    monkeypatch.setattr(
        "backend.hardware.pal.base.storage_tools", lambda: {"btrfs": True, "zfs": False, "mdadm": False}
    )
    return a, calls


def test_a_new_share_on_btrfs_is_a_subvolume(tmp_path, monkeypatch):
    a, calls = _adapter(tmp_path, monkeypatch, "btrfs")
    assert a._make_share_dir(str(tmp_path / "photos")) == "subvolume"
    assert calls == [["btrfs", "subvolume", "create", str(tmp_path / "photos")]]
    assert a._make_share_dir(str(tmp_path / "photos")) == "folder"  # already there: left as it is
    assert len(calls) == 1


def test_elsewhere_or_on_failure_a_plain_folder(tmp_path, monkeypatch):
    a, calls = _adapter(tmp_path, monkeypatch, "ext4")
    assert a._make_share_dir(str(tmp_path / "docs")) == "folder" and not calls
    assert (tmp_path / "docs").is_dir()
    a, calls = _adapter(tmp_path, monkeypatch, "btrfs", code=1)
    assert a._make_share_dir(str(tmp_path / "music")) == "folder" and len(calls) == 1
    assert (tmp_path / "music").is_dir()
