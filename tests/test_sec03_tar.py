"""SEC-03: archive extraction must not write outside the destination."""

import io
import os
import tarfile
import time

import pytest

from backend.services.app_backup import is_safe_tar_member
from backend.services.fs_transfer import TransferTaskStatus, transfer_manager


def _tar(path, entries):
    with tarfile.open(path, "w") as tf:
        for kind, name, extra in entries:
            info = tarfile.TarInfo(name)
            if kind == "file":
                data = extra.encode()
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
            elif kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = extra
                tf.addfile(info)
            elif kind == "hard":
                info.type = tarfile.LNKTYPE
                info.linkname = extra
                tf.addfile(info)


def _extract(archive, dest):
    task = transfer_manager.submit_archive_extract(str(archive), str(dest))
    for _ in range(100):
        if task.status in (TransferTaskStatus.COMPLETED, TransferTaskStatus.FAILED):
            break
        time.sleep(0.05)
    return task


@pytest.mark.parametrize(
    "entries",
    [
        [("sym", "evil", "@OUT@"), ("file", "evil/pwn.txt", "x")],
        [("sym", "evil", "../../outside"), ("file", "evil/pwn.txt", "x")],
        [("hard", "evil", "@OUT@/secret.txt")],
    ],
)
def test_link_escapes_are_refused(tmp_path, entries):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    entries = [(k, n, e.replace("@OUT@", str(outside))) for k, n, e in entries]
    archive = tmp_path / "a.tar"
    _tar(archive, entries)
    dest = tmp_path / "dest" / "inner"
    task = _extract(archive, dest)
    assert task.status == TransferTaskStatus.FAILED
    assert not (outside / "pwn.txt").exists()
    assert os.listdir(outside) == ["secret.txt"]
    assert not os.path.lexists(dest / "evil")


def test_normal_archive_with_internal_symlink_extracts(tmp_path):
    archive = tmp_path / "ok.tar"
    _tar(archive, [("file", "dir/a.txt", "hello"), ("sym", "dir/link", "a.txt")])
    dest = tmp_path / "dest"
    task = _extract(archive, dest)
    assert task.status == TransferTaskStatus.COMPLETED, task.error
    assert (dest / "dir" / "link").read_text() == "hello"


def test_app_backup_member_check(tmp_path):
    def member(kind, name, link):
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = link
        return info

    root = str(tmp_path)
    assert not is_safe_tar_member(member(tarfile.SYMTYPE, "x", "/etc"), root)
    assert not is_safe_tar_member(member(tarfile.LNKTYPE, "a/b/x", "../../etc/passwd"), root)
    assert not is_safe_tar_member(member(tarfile.CHRTYPE, "dev", ""), root)
    assert is_safe_tar_member(member(tarfile.SYMTYPE, "a/x", "../b"), root)
