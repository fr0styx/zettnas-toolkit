"""Catalog, sync, calendar, WebSocket origin, first-time password and fan confirm:
regression tests for the 2026-10 security audit (F01 F06 F09 F12 F13 F17)."""

import os
import secrets
import stat
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend import config
from backend.users_db import create_user


def _session(client, prefix="cu"):
    name = f"{prefix}{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="share_user")
    r = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# ---------------------------------------------------------------- F09 calendar


@pytest.fixture
def calendar_file(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.api.calendar.CALENDAR_DATA_FILE", str(tmp_path / "calendar_data.json"))
    monkeypatch.setattr("backend.api.calendar.DATA_DIR", str(tmp_path))
    return tmp_path / "calendar_data.json"


def test_calendar_notes_are_private_to_their_owner(client, calendar_file):
    alice, bob = _session(client, "ca"), _session(client, "cb")
    note = {"date": "2026-10-19", "title": "Alice only", "description": "private"}
    note_id = client.post("/api/calendar/notes", json=note, headers=alice).json()["note"]["id"]

    assert [e["title"] for e in client.get("/api/calendar/events", headers=alice).json()["events"]] == ["Alice only"]
    assert client.get("/api/calendar/events", headers=bob).json()["events"] == []
    assert client.patch(f"/api/calendar/notes/{note_id}", json={"title": "x"}, headers=bob).status_code == 404
    assert client.delete(f"/api/calendar/notes/{note_id}", headers=bob).status_code == 404
    assert "BEGIN:VEVENT" not in client.get("/api/calendar/export", headers=bob).text
    assert client.delete(f"/api/calendar/notes/{note_id}", headers=alice).status_code == 200


def test_calendar_feeds_and_their_urls_stay_with_their_owner(client, calendar_file):
    from backend.api import calendar as cal

    alice, bob = _session(client, "fa"), _session(client, "fb")
    with patch.object(cal, "validate_public_url", return_value=(True, "")):
        r = client.post(
            "/api/calendar/feeds",
            json={"name": "Work", "url": "https://calendar.example.com/private-token.ics", "enabled": False},
            headers=alice,
        )
    assert r.status_code == 200, r.text
    feed_id = r.json()["feed"]["id"]
    assert client.get("/api/calendar/feeds", headers=bob).json()["feeds"] == []
    assert client.delete(f"/api/calendar/feeds/{feed_id}", headers=bob).status_code == 404
    with patch.object(cal, "validate_public_url", return_value=(True, "")):
        r = client.post(
            "/api/calendar/feeds",
            json={"id": feed_id, "name": "Taken", "url": "https://calendar.example.com/b.ics", "enabled": False},
            headers=bob,
        )
    assert r.status_code == 404
    assert client.get("/api/calendar/feeds", headers=alice).json()["feeds"][0]["name"] == "Work"


def test_notes_saved_before_owners_stay_with_administrators(client, auth_headers, calendar_file):
    import json

    calendar_file.write_text(
        json.dumps({"notes": [{"id": "old", "date": "2026-01-01", "title": "Legacy"}], "feeds": [], "feed_events": []})
    )
    assert [e["id"] for e in client.get("/api/calendar/events", headers=auth_headers).json()["events"]] == ["old"]
    assert client.get("/api/calendar/events", headers=_session(client)).json()["events"] == []


# ---------------------------------------------------------------- F12 WebSocket origin


def _ws(origin, host, client_ip="203.0.113.9", **extra):
    ws = MagicMock()
    ws.headers = {"origin": origin, "host": host, **extra}
    ws.client = SimpleNamespace(host=client_ip)
    return ws


def test_websocket_origin_needs_the_same_port_and_scheme():
    from backend.auth import validate_websocket_origin

    assert validate_websocket_origin(_ws("http://nas.lan:8082", "nas.lan:8082"), is_cookie_auth=True)
    assert not validate_websocket_origin(_ws("http://nas.lan:9000", "nas.lan:8082"), is_cookie_auth=True)
    assert not validate_websocket_origin(_ws("http://localhost:3000", "nas.lan:8082"), is_cookie_auth=True)
    # X-Forwarded-Host counts only when the request comes from a trusted proxy.
    proxied = {"x-forwarded-host": "nas.example.org"}
    assert not validate_websocket_origin(
        _ws("https://nas.example.org", "127.0.0.1:8082", **proxied), is_cookie_auth=True
    )
    assert validate_websocket_origin(
        _ws("https://nas.example.org", "127.0.0.1:8082", client_ip="127.0.0.1", **proxied), is_cookie_auth=True
    )


# ---------------------------------------------------------------- F13 first-time password


def test_fresh_install_gets_a_first_time_password_not_admin(tmp_path, monkeypatch):
    from backend.passwords import verify_password
    from backend.users_db import get_user_by_id, init_users_db, update_user_password

    admin_id = "admin-00000000-0000-0000-0000-000000000001"
    monkeypatch.setenv("ZETTNAS_ALLOW_DEFAULT_PASSWORD", "0")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "SECURITY_FILE", str(tmp_path / "security.json"))
    monkeypatch.setattr(config, "STORED_PASSWORD_HASH", config.STORED_PASSWORD_HASH)
    db = str(tmp_path / "users.db")
    init_users_db(db)

    admin = get_user_by_id(admin_id, db_path=db)
    path = config.initial_password_file()
    with open(path, encoding="utf-8") as f:
        first = f.read().strip()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not verify_password("admin", admin["password_hash"])
    assert verify_password(first, admin["password_hash"])
    assert admin["must_change_password"]
    assert config.is_using_default_password()  # the setup wizard still asks for a new one

    update_user_password(admin_id, "Chosen-Pass-42", db_path=db)
    assert not os.path.exists(path)


# ---------------------------------------------------------------- F06 rclone locations


def test_sync_locations_are_configured_remotes_or_pool_paths(tmp_path, monkeypatch):
    from backend.services.rclone_engine import RcloneEngine

    pool = tmp_path / "pool"
    (pool / "photos").mkdir(parents=True)
    conf = tmp_path / "rclone.conf"
    conf.write_text("[offsite]\ntype = local\n")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    engine = RcloneEngine.__new__(RcloneEngine)
    engine.config_file = str(conf)

    assert engine.checked_location("offsite:backups/photos") == "offsite:backups/photos"
    assert engine.checked_location(str(pool / "photos")) == str(pool / "photos")
    for bad in ("--config=/tmp/x", ":local:/etc", "other:path", "offsite,opt=1:x", "/etc", "relative/path", "a\nb"):
        with pytest.raises(ValueError):
            engine.checked_location(bad)
    assert engine.checked_location("/etc", confine_local=False) == "/etc"  # storage admins


def test_backup_operator_cannot_sync_outside_the_pool(client):
    name = f"bo{secrets.token_hex(3)}"
    create_user(name, name, "GoodPass123!", role_id="backup_operator")
    r = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    r = client.post("/api/remotes/sync", json={"src": "/", "dst": "/tmp/copy-of-root"}, headers=headers)
    assert r.status_code == 400


# ---------------------------------------------------------------- F01 catalog templates


def test_template_volume_keys_are_folder_names():
    from backend.services.app_catalog import parse_portainer_volumes, sanitize_volume_map

    vols = sanitize_volume_map(
        {"/": "/host", "../../etc": "/etc-in-app", "config": "/config", "/var/run/docker.sock": "/s"}
    )
    assert all("/" not in k and k not in (".", "..") for k in vols)
    assert vols["config"] == "/config"
    assert set(vols.values()) == {"/host", "/etc-in-app", "/config", "/s"}
    assert all("/" not in k for k in parse_portainer_volumes({"/": "/rootfs"}))


def _deploy(app, tmp_path, image_present=False):
    from backend.services import app_catalog

    calls = []

    def fake_docker(method, path, *args, **kwargs):
        calls.append((method, path, kwargs.get("body")))
        if "create" in path:
            return 201, {"Id": "cid"}
        if path.endswith("/json"):
            return (200, {}) if image_present and path.startswith("/images/") else (404, {})
        return 200, {}

    with (
        patch.object(app_catalog, "get_catalog_app", return_value=app),
        patch.object(app_catalog, "_docker_request", side_effect=fake_docker),
        patch.object(app_catalog, "check_port_available_detailed", return_value=(True, None)),
    ):
        events = list(app_catalog.stream_deploy_catalog_app(app["id"], host_port=18080, storage_root=str(tmp_path)))
    return events, calls


def test_cached_template_with_a_host_path_volume_is_refused(tmp_path):
    app = {
        "id": "evil",
        "name": "Evil",
        "image": "example/app:1",
        "source_id": "community",
        "volumes": {"/": "/host"},
        "default_port": 18080,
    }
    events, calls = _deploy(app, tmp_path)
    assert events[-1]["step"] == "error" and "host folders" in events[-1]["message"]
    assert not any("create" in c[1] for c in calls)


def test_community_template_gets_no_host_level_access(tmp_path):
    # 1.9.x does not apply template capabilities, devices or privileged mode at all.
    app = {
        "id": "dev",
        "name": "Dev",
        "image": "example/app:1",
        "source_id": "community",
        "volumes": {"config": "/config"},
        "cap_add": ["SYS_ADMIN"],
        "privileged": True,
        "devices": ["/dev/null"],
        "default_port": 18080,
    }
    _, calls = _deploy(app, tmp_path, image_present=True)
    body = next(c[2] for c in calls if "/containers/create" in c[1])
    host = body["HostConfig"]
    assert not host.get("CapAdd") and not host.get("Privileged") and not host.get("Devices")
    assert all(b.startswith(str(tmp_path)) for b in host["Binds"])


# ---------------------------------------------------------------- F17 fan confirm summary


def test_fan_confirm_summary_names_zero_rpm():
    from backend.services.ai_actions import describe

    assert "Zero-RPM on" in describe("set_fan_profile", {"profile": "quiet", "zero_rpm_enabled": True})
    assert "Zero-RPM" not in describe("set_fan_profile", {"profile": "quiet"})
