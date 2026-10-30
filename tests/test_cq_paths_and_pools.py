"""CodeQL findings that were real: an app's data folder is never a system folder or ZettNAS's
own, and a pool name in a URL can't be a zpool option."""

import os

from backend.services import app_catalog as ac


def test_app_dir_is_made_under_a_safe_root(tmp_path):
    app_dir, problem = ac.app_dir_for(str(tmp_path), "jellyfin")
    assert problem == "" and app_dir == os.path.realpath(tmp_path / "jellyfin") and os.path.isdir(app_dir)


def test_unsafe_roots_are_refused(monkeypatch, tmp_path):
    for bad in ("", "relative/apps", "/etc", "/", "/usr/lib/x", "/proc/1"):
        assert ac.app_dir_for(bad, "x")[1], bad
    monkeypatch.setattr("backend.fsutil.is_protected", lambda p: p.startswith(str(tmp_path / "zn")))
    assert ac.app_dir_for(str(tmp_path / "zn"), "x")[1]  # ZettNAS's own folder
    assert ac.app_dir_for(str(tmp_path), "zn")[1]  # an app named after it, under a fine root
    assert ac.app_dir_for(str(tmp_path), "../escape")[1]


def test_a_folder_that_cant_be_made_is_an_error(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert "couldn't be made" in ac.app_dir_for(str(blocker), "app")[1]


def test_install_stops_on_an_unsafe_root():
    events = list(ac.stream_deploy_catalog_app("uptime-kuma", host_port=3001, storage_root="/etc"))
    assert events[-1]["step"] == "error" and events[-1]["error"] == "Unsafe folder"


def test_pool_names_in_urls_cant_be_options(client, auth_headers):
    for bad in ("-a", "--force", "a b"):
        r = client.post(f"/api/storage/pools/{bad}/export", headers=auth_headers, json={})
        assert r.status_code == 422, bad
    r = client.put("/api/protection/scrub/-a", headers=auth_headers, json={"enabled": True})
    assert r.status_code == 422


def test_a_pool_rename_is_one_name():
    import pytest
    from pydantic import ValidationError

    from backend.api.storage import StoragePoolRenameRequest

    for bad in ("../other", "-f", "a/b"):
        with pytest.raises(ValidationError):
            StoragePoolRenameRequest(new_name=bad)
    assert StoragePoolRenameRequest(new_name="tank2").new_name == "tank2"


def test_a_pool_import_is_checked():
    import pytest
    from pydantic import ValidationError

    from backend.api.storage import StoragePoolImportRequest

    ok = StoragePoolImportRequest(pool_id="usbpool", fs_type="btrfs", target_mount="/mnt/disks/usbpool")
    assert ok.target_mount == "/mnt/disks/usbpool"
    for bad in (
        {"pool_id": "-a"},
        {"pool_id": "../x"},
        {"pool_id": "p", "target_mount": "/etc"},
        {"pool_id": "p", "target_mount": "rel"},
    ):
        with pytest.raises(ValidationError):
            StoragePoolImportRequest(**bad)
