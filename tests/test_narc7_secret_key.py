"""NARC-7: the secret key is saved durably, never over another, and ZettNAS won't run without it."""

import os

import pytest

from backend import config


def test_the_key_is_written_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    config._persist_key("a" * 64, replace=False)
    assert (tmp_path / "secret.key").read_text() == "a" * 64
    assert oct((tmp_path / "secret.key").stat().st_mode & 0o777) == "0o600"
    with pytest.raises(FileExistsError):
        config._persist_key("b" * 64, replace=False)  # never over a key that exists
    assert (tmp_path / "secret.key").read_text() == "a" * 64
    assert [p.name for p in tmp_path.iterdir()] == ["secret.key"]  # no temporary file left


def test_an_empty_key_file_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    (tmp_path / "secret.key").write_text("")
    config._persist_key("c" * 64, replace=True)
    assert (tmp_path / "secret.key").read_text() == "c" * 64


def test_no_saved_key_means_no_start(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    monkeypatch.delenv("SECRET_KEY", raising=False)

    def cant(key, replace):
        raise OSError("read-only file system")

    monkeypatch.setattr(config, "_persist_key", cant)
    monkeypatch.setattr(config, "test_mode", lambda: False)  # the released image
    with pytest.raises(RuntimeError, match="Cannot save the secret key"):
        config._get_or_create_secret_key()
    monkeypatch.setattr(config, "test_mode", lambda: True)
    assert len(config._get_or_create_secret_key()) == 64


def test_json_writes_sync_their_folder(tmp_path, monkeypatch):
    from backend import fsutil

    synced = []
    monkeypatch.setattr(fsutil, "_fsync_dir", lambda d: synced.append(d))
    fsutil.atomic_write_json(str(tmp_path / "x.json"), {"a": 1})
    assert synced == [str(tmp_path)]
    fsutil._fsync_dir(str(tmp_path / "missing"))  # a folder that isn't there is not an error
    assert os.path.exists(tmp_path / "x.json")
