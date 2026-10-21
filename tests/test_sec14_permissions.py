"""SEC-14: secrets in DATA_DIR are not readable by other users."""

import os
import stat

from backend.services.data_permissions import harden_data_permissions


def _mode(p):
    return stat.S_IMODE(os.lstat(p).st_mode)


def test_secret_files_and_folders_are_restricted(tmp_path):
    for name in ("secret.key", "security.json", "users.db", "events.json"):
        (tmp_path / name).write_text("x")
        os.chmod(tmp_path / name, 0o777)
    (tmp_path / "rclone").mkdir()
    (tmp_path / "rclone" / "rclone.conf").write_text("token")
    os.chmod(tmp_path / "rclone", 0o777)
    os.chmod(tmp_path / "rclone" / "rclone.conf", 0o666)
    (tmp_path / "outside.txt").write_text("x")
    os.symlink(tmp_path / "outside.txt", tmp_path / "webdav_config.json")
    os.chmod(tmp_path / "outside.txt", 0o644)

    assert harden_data_permissions(str(tmp_path)) == 5
    for name in ("secret.key", "security.json", "users.db"):
        assert _mode(tmp_path / name) == 0o600
    assert _mode(tmp_path / "events.json") == 0o777  # not a secret
    assert _mode(tmp_path / "rclone") == 0o700
    assert _mode(tmp_path / "rclone" / "rclone.conf") == 0o600
    assert _mode(tmp_path / "outside.txt") == 0o644  # symlinks are not followed
    assert harden_data_permissions(str(tmp_path)) == 0
