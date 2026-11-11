"""The data snapshot survives a file replaced while it is copied (CI smoke test of 753c081)."""

import shutil
from unittest.mock import patch

from backend.services import data_snapshot as ds


def test_half_written_files_are_skipped(tmp_path):
    (tmp_path / ".tmp-abc123").write_text("x")
    (tmp_path / "smb.conf.tmp").write_text("x")
    (tmp_path / "smb.conf").write_text("x")
    assert sorted(ds._skip_special_files(str(tmp_path), [".tmp-abc123", "smb.conf.tmp", "smb.conf"])) == [
        ".tmp-abc123",
        "smb.conf.tmp",
    ]


def test_a_vanished_file_is_forgiven_a_real_error_is_not(tmp_path):
    gone = str(tmp_path / "gone")
    with patch.object(ds.shutil, "copytree", side_effect=shutil.Error([(gone, "/x/gone", "No such file")])):
        ds._copytree_settled(str(tmp_path), str(tmp_path / "out"))  # no error
    there = tmp_path / "there"
    there.write_text("x")
    with patch.object(ds.shutil, "copytree", side_effect=shutil.Error([(str(there), "/x/there", "Permission denied")])):
        try:
            ds._copytree_settled(str(tmp_path), str(tmp_path / "out2"))
        except shutil.Error as e:
            assert e.args[0][0][0] == str(there)
        else:
            raise AssertionError("a real copy error was swallowed")
