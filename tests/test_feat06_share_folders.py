"""FEAT-06: an app's folder (Syncthing's synced folders, Nextcloud's files, music) on a share."""

import os

import pytest

from backend.services import app_catalog as ac


@pytest.fixture
def shares(tmp_path, monkeypatch):
    music = tmp_path / "Music"
    family = tmp_path / "Family"
    music.mkdir()
    family.mkdir()
    found = {"Music": str(music), "Family": str(family)}
    monkeypatch.setattr(ac, "share_mounts", lambda: dict(found))
    return found


def test_only_built_in_templates_name_share_folders():
    sync = ac.get_catalog_app("syncthing")
    assert sync["share_folders"] == {"data": "Synced folders"}
    assert ac.share_folder_choices(sync) == [{"key": "data", "label": "Synced folders", "target": "/data1"}]
    assert ac.share_folder_choices({**sync, "source_id": "community"}) == []
    # a folder the template doesn't mount isn't offered
    assert ac.share_folder_choices({"volumes": {"a": "/a"}, "share_folders": {"b": "B"}}) == []
    assert ac.share_folder_choices(ac.get_catalog_app("adguardhome")) == []


def test_picks_are_checked(shares):
    sync = ac.get_catalog_app("syncthing")
    assert ac.share_folder_paths(sync, None) == ({}, None)
    assert ac.share_folder_paths(sync, {"data": ""}) == ({}, None)
    assert ac.share_folder_paths(sync, {"data": "Family"}) == ({"data": shares["Family"]}, None)
    _, why = ac.share_folder_paths(sync, {"config": "Family"})
    assert "can't keep config on a share" in why
    _, why = ac.share_folder_paths(sync, {"data": "../etc"})
    assert "no share called ../etc" in why


def test_share_listing_failure_is_a_reason(monkeypatch):
    def broken():
        raise OSError("no storage platform")

    monkeypatch.setattr(ac, "share_mounts", broken)
    _, why = ac.share_folder_paths(ac.get_catalog_app("syncthing"), {"data": "Family"})
    assert "couldn't be listed" in why


def test_share_mounts_lists_existing_folders(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from backend.hardware import pal_storage

    there = tmp_path / "Photos"
    there.mkdir()
    listed = [
        SimpleNamespace(name="Photos", mountpoint=str(there)),
        SimpleNamespace(name="Gone", mountpoint=str(tmp_path / "gone")),
        SimpleNamespace(name="", mountpoint=str(there)),
    ]
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: SimpleNamespace(list_shares=lambda: listed))
    assert ac.share_mounts() == {"Photos": str(there)}


def test_binds(tmp_path, shares, monkeypatch):
    monkeypatch.setattr(ac, "media_library_bind", lambda app: None)
    app_dir = str(tmp_path / "apps" / "syncthing")
    sync = ac.get_catalog_app("syncthing")
    binds = ac.app_binds(sync, app_dir, {"data": shares["Family"]})
    assert f"{shares['Family']}:/data1:rw" in binds
    assert f"{app_dir}/config:/config:rw" in binds
    assert not os.path.exists(f"{app_dir}/data")  # no empty folder left behind

    # a media library picked for Jellyfin is mounted read-only
    jelly = ac.get_catalog_app("jellyfin")
    assert f"{shares['Music']}:/media:ro" in ac.app_binds(jelly, app_dir, {"media": shares["Music"]})
    # without a pick it is the media share found by name, as before
    monkeypatch.setattr(ac, "media_library_bind", lambda app: "/mnt/user/media:/media:ro")
    assert "/mnt/user/media:/media:ro" in ac.app_binds(jelly, app_dir, {})


def test_a_share_is_never_re_owned(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "chown", lambda p, u, g: calls.append(p))
    app_dir = tmp_path / "fb"
    (app_dir / "config").mkdir(parents=True)
    ac._own_volumes(ac.get_catalog_app("filebrowser"), str(app_dir))
    assert calls == [str(app_dir / "config")]  # srv lives on a share, database wasn't made


def test_install_refuses_a_bad_share_before_anything_runs(shares, monkeypatch):
    called = []
    monkeypatch.setattr(ac, "_docker_request", lambda *a, **k: called.append(a) or (404, {}))
    events = list(ac.stream_deploy_catalog_app("syncthing", share_folders={"data": "Nowhere"}))
    assert events[-1]["step"] == "error" and "no share called Nowhere" in events[-1]["message"]
    assert called == []


def test_install_mounts_the_share(tmp_path, shares, monkeypatch):
    seen = {}

    def stop_after_compose(app_id, *a, **k):
        seen["overrides"] = k.get("volume_overrides")
        return {"compose_yaml": "services: {}\n"}

    monkeypatch.setattr(ac, "generate_compose_for_app", stop_after_compose)
    monkeypatch.setattr(ac, "media_library_bind", lambda app: None)
    monkeypatch.setattr(ac, "_docker_request", lambda *a, **k: (500, {}))
    monkeypatch.setattr(ac, "check_port_available_detailed", lambda *a, **k: (False, "test"))
    list(ac.stream_deploy_catalog_app("syncthing", storage_root=str(tmp_path), share_folders={"data": "Family"}))
    assert seen["overrides"] == {"data": shares["Family"]}


def test_api(client, auth_headers, shares):
    got = client.get("/api/docker/catalog/syncthing/share-folders", headers=auth_headers).json()
    assert got["folders"] == [{"key": "data", "label": "Synced folders", "target": "/data1"}]
    assert {s["name"] for s in got["shares"]} == {"Music", "Family"}
    assert client.get("/api/docker/catalog/adguardhome/share-folders", headers=auth_headers).json() == {
        "folders": [],
        "shares": [],
    }
    assert client.get("/api/docker/catalog/no-such-app/share-folders", headers=auth_headers).status_code == 404
    assert client.get("/api/docker/catalog/bad%20id/share-folders", headers=auth_headers).status_code == 400

    comp = client.post(
        "/api/docker/catalog/syncthing/compose", headers=auth_headers, json={"share_folders": {"data": "Family"}}
    )
    assert comp.status_code == 200 and f"{shares['Family']}:/data1" in comp.json()["compose_yaml"]
    bad = client.post(
        "/api/docker/catalog/syncthing/compose", headers=auth_headers, json={"share_folders": {"data": "Nope"}}
    )
    assert bad.status_code == 400


def test_api_without_shares(client, auth_headers, monkeypatch):
    def broken():
        raise OSError("down")

    monkeypatch.setattr(ac, "share_mounts", broken)
    got = client.get("/api/docker/catalog/nextcloud/share-folders", headers=auth_headers).json()
    assert got["folders"][0]["key"] == "data" and got["shares"] == []
