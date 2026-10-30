"""B19: guessing encrypted-folder passwords, sync pairs that replace each other, binds and shares
that hold ZettNAS's data, and WebDAV/SFTP never showing encrypted files (NSEC-4, NUX-6, NSEC-9, NSEC-5)."""

import pytest

from backend.services import encrypted_folders as ef


def test_wrong_passwords_lock_a_folder_for_a_while(monkeypatch):
    monkeypatch.setattr(ef, "_settings", lambda: {"folders": {"Taxes": {"share": "Family"}}})
    monkeypatch.setattr(ef, "is_unlocked", lambda name: False)
    monkeypatch.setattr(ef, "_share_path", lambda share: "/mnt/user/Family")

    def wrong(*a, **k):
        raise ef.EncryptedFolderError("That password is wrong.")

    monkeypatch.setattr(ef, "_mount", wrong)
    ef._wrong.clear()
    for _ in range(ef.GUESS_LIMIT):
        with pytest.raises(ef.EncryptedFolderError, match="wrong"):
            ef.unlock("Taxes", "guess")
    with pytest.raises(ef.EncryptedFolderError, match="Too many wrong passwords"):
        ef.unlock("Taxes", "the real one")
    ef._wrong["Taxes"] = [t - ef.GUESS_WINDOW for t in ef._wrong["Taxes"]]  # time passes
    monkeypatch.setattr(ef, "_mount", lambda *a, **k: None)
    assert ef.unlock("Taxes", "the real one")["unlocked"] and "Taxes" not in ef._wrong


def test_a_folder_password_is_long():
    with pytest.raises(ValueError, match="at least 12"):
        ef._check_password("short pass")
    ef._check_password("three long words here")


def test_unlocking_is_rate_limited():
    import inspect

    from backend.api import encrypted_folders as api

    assert 'rate_limit("ef.unlock"' in inspect.getsource(api)


def test_a_new_sync_pair_never_replaces_another(tmp_path, monkeypatch):
    from backend.services import two_way_sync as tws

    monkeypatch.setattr(tws, "PAIRS_FILE", str(tmp_path / "pairs.json"))
    ok = lambda p: p  # noqa: E731
    first = tws.save_pair("sync", "家庭照片", "/mnt/user/Photos", "gdrive:photos", check=ok, new=True)
    second = tws.save_pair("sync", "工作文件", "/mnt/user/Work", "gdrive:work", check=ok, new=True)
    third = tws.save_pair("sync", "学校", "/mnt/user/School", "gdrive:school", check=ok, new=True)
    assert (first["id"], second["id"], third["id"]) == ("sync", "sync-2", "sync-3")
    assert {p["local"] for p in tws.list_pairs()} == {"/mnt/user/Photos", "/mnt/user/Work", "/mnt/user/School"}
    # changing an existing pair keeps its id
    assert tws.save_pair("sync-2", "工作文件", "/mnt/user/Work", "gdrive:work2", check=ok)["id"] == "sync-2"


def test_a_folder_that_contains_zettnas_data_is_host_access(monkeypatch):
    from backend import docker_proxy

    monkeypatch.setattr(docker_proxy, "_app_folders", lambda: ["/mnt/user/appdata/zettnas/data"])
    assert docker_proxy._risky_host_path("/mnt/user/appdata") == "/mnt/user/appdata"
    assert docker_proxy._risky_host_path("/mnt/user") == "/mnt/user"
    assert docker_proxy._risky_host_path("/mnt/user/Family") is None


def test_the_share_picker_leaves_out_system_shares_and_zettnas_data(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from backend.hardware import pal_storage
    from backend.services import app_catalog

    for n in ("Family", "appdata", "Everything", "system"):
        (tmp_path / n).mkdir()
    (tmp_path / "Everything" / "zettnas-data").mkdir()
    listed = [
        SimpleNamespace(name=n, mountpoint=str(tmp_path / n)) for n in ("Family", "appdata", "Everything", "system")
    ]
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_shares=lambda: listed))
    monkeypatch.setattr("backend.fsutil.protected_dirs", lambda: [str(tmp_path / "Everything" / "zettnas-data")])
    assert app_catalog.share_mounts() == {"Family": str(tmp_path / "Family")}


def test_webdav_and_sftp_hide_the_encrypted_files():
    from backend.fsutil import protected_rclone_excludes

    flags = protected_rclone_excludes("/mnt/user")
    assert "**/.zettnas-encrypted/**" in flags and "**/.zettnas-encrypted" in flags
