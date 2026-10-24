"""Cloud remotes (rclone): names can't point at the remotes folder or above it, passwords never
go on a command line, and the masked value shown in lists never replaces a stored password."""

import configparser
import subprocess

import pytest

from backend.services import rclone_engine as re_mod
from backend.services.rclone_engine import VALID_REMOTE_NAME, RcloneEngine, check_remote_name


@pytest.mark.parametrize("name", [".", "..", ".hidden", "-x", "a/b", "", "x" * 65])
def test_names_that_could_leave_the_remotes_folder(name):
    assert not VALID_REMOTE_NAME.fullmatch(name)
    with pytest.raises(ValueError):
        check_remote_name(name)


@pytest.mark.parametrize("name", ["onedrive", "my-drive.2", "_b2", "Box_1"])
def test_ordinary_names(name):
    assert check_remote_name(name) == name


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(re_mod.config, "RCLONE_CONFIG_FILE", str(tmp_path / "rclone" / "rclone.conf"))
    monkeypatch.setattr(re_mod.config, "RCLONE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(re_mod.config, "REMOTES_PATH", str(tmp_path / "remotes"))
    e = RcloneEngine()
    monkeypatch.setattr(e, "_get_rclone_bin", lambda: "/usr/bin/rclone")
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        if cmd[1] == "obscure":
            return subprocess.CompletedProcess(cmd, 0, "OBSC(" + (kw.get("input") or "") + ")\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(re_mod.subprocess, "run", run)
    e.calls = calls
    return e


def _stored(engine, name, key):
    cfg = configparser.RawConfigParser()
    cfg.read(engine.config_file)
    return cfg.get(name, key)


def test_password_goes_to_rclone_on_stdin(engine):
    assert engine._obscure_password("hunter2-secret") == "OBSC(hunter2-secret)"
    cmd, stdin = engine.calls[-1]
    assert cmd == ["/usr/bin/rclone", "obscure", "-"] and stdin == "hunter2-secret"
    assert not any("hunter2-secret" in " ".join(c) for c, _ in engine.calls)
    assert engine._obscure_password("") == ""


def test_a_failed_obscure_is_an_error_not_plaintext(engine, monkeypatch):
    monkeypatch.setattr(re_mod.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    with pytest.raises(ValueError):
        engine._obscure_password("secret")


def test_saving_keeps_the_stored_password_for_the_mask_or_the_same_value(engine, monkeypatch):
    monkeypatch.setattr(engine, "_resolve_onedrive_metadata", lambda p: p, raising=False)
    engine.create_remote("nas2", "webdav", {"url": "https://dav.example", "user": "me", "pass": "first-pass"})
    assert _stored(engine, "nas2", "pass") == "OBSC(first-pass)"
    engine.create_remote("nas2", "webdav", {"url": "https://dav.example", "user": "me", "pass": "********"})
    assert _stored(engine, "nas2", "pass") == "OBSC(first-pass)"  # the mask didn't become the password
    engine.create_remote("nas2", "webdav", {"pass": "OBSC(first-pass)"})
    assert _stored(engine, "nas2", "pass") == "OBSC(first-pass)"  # not obscured twice
    engine.create_remote("nas2", "webdav", {"pass": "new-pass"})
    assert _stored(engine, "nas2", "pass") == "OBSC(new-pass)"


@pytest.mark.parametrize(
    "method", ["mount_remote", "unmount_remote", "delete_remote", "list_remote_files", "test_remote"]
)
def test_every_entry_point_checks_the_name(engine, method):
    with pytest.raises(ValueError):
        getattr(engine, method)("..")
    assert not any(c[0][0] in ("umount", "fusermount", "fusermount3") for c in engine.calls)


def test_route_reports_a_bad_name_as_the_callers_mistake(client, auth_headers):
    r = client.post("/api/remotes/.hidden/mount", json={}, headers=auth_headers)
    assert r.status_code == 400
    r = client.post("/api/remotes/ok/mount", json={"vfs_cache": "--rc"}, headers=auth_headers)
    assert r.status_code == 422
