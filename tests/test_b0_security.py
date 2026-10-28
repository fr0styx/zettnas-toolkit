"""Batch 0 of the v1.10 audit: each attack from the audit must fail.

SEC-1 WebDAV without sign-in, SEC-2 host access through container recreate, SEC-3 the app's own
data folder through the file features, SEC-4 tokens that outlive their owner's role, SEC-5/REL-1
backups that upload plaintext or mirror an empty source, AI-11 file contents over MCP.
"""

import json
import os
import secrets
import shutil

import pytest

from backend import config, fsutil
from backend.api import auth as auth_api
from backend.users_db import (
    cap_token_scopes,
    create_scoped_api_token,
    create_user,
    get_user_by_username,
    update_user_password,
    update_user_profile,
    validate_scoped_api_token,
)

ADMIN = auth_api.ADMIN_USER_ID


def _name(prefix):
    return f"{prefix}{secrets.token_hex(3)}"


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ SEC-3 the app's own folders
@pytest.fixture
def data_alias(paths):
    """The data folder seen a second time inside the pool, as on Unraid (/mnt/user/appdata/...)."""
    fsutil.reset_protected_dirs()
    marker_id = fsutil._data_marker(os.path.realpath(paths["data"]))
    app_dir = os.path.join(paths["pool"], "appdata", "zettnas-toolkit")
    alias = os.path.join(app_dir, "data")
    os.makedirs(alias, exist_ok=True)
    with open(os.path.join(alias, fsutil.DATA_MARKER), "w") as f:
        f.write(marker_id)
    with open(os.path.join(alias, "users.db"), "w") as f:
        f.write("secret users")
    with open(os.path.join(app_dir, "docker-compose.yml"), "w") as f:
        f.write("services: {}")
    os.makedirs(os.path.join(paths["pool"], "appdata", "plex"), exist_ok=True)
    fsutil.reset_protected_dirs()
    yield alias
    shutil.rmtree(os.path.join(paths["pool"], "appdata"), ignore_errors=True)
    fsutil.reset_protected_dirs()


def test_the_data_folder_alias_is_refused_everywhere(data_alias, paths):
    pool = paths["pool"]
    assert fsutil.resolve_within(os.path.join(data_alias, "users.db"), [pool]) is None
    assert fsutil.resolve_within(data_alias, [pool]) is None
    # the install folder next to it (compose file, .env) too, but not other apps' folders
    assert fsutil.resolve_within(os.path.dirname(data_alias), [pool]) is None
    assert fsutil.resolve_within(os.path.join(pool, "appdata", "plex"), [pool])
    # a caller that deliberately works inside the data folder still can
    assert fsutil.resolve_within(os.path.join(paths["data"], "x.json"), [paths["data"]])


def test_walks_and_rclone_servers_skip_the_data_folder(data_alias, paths):
    pool = paths["pool"]
    seen = []
    for root, dirs, files in os.walk(pool):
        fsutil.prune_protected(root, dirs)
        seen += [os.path.join(root, f) for f in files]
    assert not any("users.db" in f for f in seen)
    flags = fsutil.protected_rclone_excludes(pool)
    assert "/appdata/zettnas-toolkit/**" in flags and "/appdata/zettnas-toolkit/data/**" in flags


def test_admins_cannot_open_or_list_the_data_folder(data_alias, paths, client, auth_headers):
    from backend.api.fs import _handle_browse_logic_unfiltered

    listing = _handle_browse_logic_unfiltered(os.path.join(paths["pool"], "appdata"), dirs_only=False)
    names = [e["name"] for e in listing["dirs"]]
    assert "plex" in names and "zettnas-toolkit" not in names
    r = client.get("/api/fs/download", params={"path": os.path.join(data_alias, "users.db")}, headers=auth_headers)
    assert r.status_code in (403, 404)


# ------------------------------------------------------------------ SEC-1 WebDAV
def test_webdav_settings_refuse_no_sign_in_and_unsafe_folders(client, auth_headers, paths):
    r = client.post("/api/webdav/config", json={"auth_enabled": False}, headers=auth_headers)
    assert r.status_code == 400
    r = client.post("/api/webdav/config", json={"root_path": "/"}, headers=auth_headers)
    assert r.status_code == 400
    r = client.post("/api/webdav/config", json={"root_path": paths["data"]}, headers=auth_headers)
    assert r.status_code == 400
    r = client.post("/api/webdav/config", json={"root_path": paths["pool"], "read_only": True}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["auth_enabled"] is True


def test_webdav_settings_need_a_superadmin(client):
    name = _name("sa")
    user = create_user(name, "Storage admin", "GoodPass123!", role_id="storage_admin")
    raw, _ = create_scoped_api_token(user["id"], "t", ["storage:*", "shares:*"])
    r = client.post("/api/webdav/config", json={"read_only": True}, headers=_bearer(raw))
    assert r.status_code == 403


def test_old_unsafe_webdav_settings_are_fixed(paths):
    from backend.services.webdav_engine import WebdavEngine

    with open(config.WEBDAV_CONFIG_FILE, "w") as f:
        json.dump({"enabled": False, "auth_enabled": False, "root_path": "/"}, f)
    engine = WebdavEngine()  # ensure_config_defaults runs on creation
    stored = fsutil.read_json(config.WEBDAV_CONFIG_FILE, {})
    assert stored["auth_enabled"] is True and stored["root_path"] != "/"
    assert engine.load_config()["auth_enabled"] is True


def test_the_webdav_portal_never_lets_anyone_in_without_signing_in():
    from unittest.mock import MagicMock

    from backend.api.webdav import _get_webdav_portal_user

    req = MagicMock()
    req.cookies, req.headers = {}, {}
    req.state = MagicMock(spec=[])
    assert _get_webdav_portal_user(req, {"auth_enabled": False}) is None


# ------------------------------------------------------------------ SEC-4 tokens
def test_tokens_never_exceed_the_owners_current_role():
    name = _name("tk")
    user = create_user(name, "Was admin", "GoodPass123!", role_id="superadmin")
    raw, _ = create_scoped_api_token(user["id"], "everything", ["*"])
    assert validate_scoped_api_token(raw)["scopes"] == ["*"]
    update_user_profile(user["id"], role_id="share_user")
    scopes = validate_scoped_api_token(raw)["scopes"]
    assert "*" not in scopes and "shares:read" in scopes and "containers:manage" not in scopes


def test_cap_keeps_only_what_the_role_allows():
    assert cap_token_scopes(["containers:manage", "shares:read"], ["shares:read", "system:view"]) == ["shares:read"]
    assert cap_token_scopes(["*"], ["shares:read"]) == ["shares:read"]
    assert cap_token_scopes(["shares:read"], []) == []


def test_a_token_must_say_what_it_may_do(client, auth_headers):
    with pytest.raises(ValueError):
        create_scoped_api_token(ADMIN, "nothing", [])
    name = _name("op")
    user = create_user(name, "Operator", "GoodPass123!", role_id="app_operator")
    raw, _ = create_scoped_api_token(user["id"], "ops", ["containers:*", "system:view", "logs:read"])
    r = client.post("/api/tokens", json={"name": "no scopes given"}, headers=_bearer(raw))
    # app operators can't create tokens at all; an admin's token gets the admin's scopes
    assert r.status_code == 403
    r = client.post("/api/tokens", json={"name": "admin default"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["scopes"]


def test_an_admin_password_reset_revokes_the_users_tokens():
    name = _name("rs")
    user = create_user(name, "Reset me", "GoodPass123!", role_id="share_user")
    raw, _ = create_scoped_api_token(user["id"], "t", ["shares:read"])
    update_user_password(user["id"], "NewGoodPass456!")
    assert validate_scoped_api_token(raw)  # a routine change keeps tokens
    update_user_password(user["id"], "NewerGoodPass789!", revoke_tokens=True)
    assert validate_scoped_api_token(raw) is None


# ------------------------------------------------------------------ SEC-2 container recreate
def test_recreate_elevation_flags_only_new_host_access():
    from backend.services.container_mutator import recreate_elevation

    plain = {"Binds": ["/mnt/user/media:/media"]}
    assert recreate_elevation(plain, {"HostConfig": plain}, "linuxserver/plex:1", "linuxserver/plex:2") == []
    root = {"HostConfig": {"Binds": ["/:/host"]}}
    assert any("/" in r for r in recreate_elevation(plain, root, "a/b:1", "a/b:1"))
    priv = {"Privileged": True}
    assert recreate_elevation(priv, {"HostConfig": priv}, "a/b:1", "a/b:2") == []
    assert recreate_elevation(priv, {"HostConfig": priv}, "a/b:1", "evil/image:1")
    net = {"HostConfig": {"NetworkMode": "host"}}
    assert recreate_elevation({}, net, "a/b:1", "a/b:1")


def test_recreate_with_host_access_needs_superadmin_and_confirmation(client, auth_headers, monkeypatch):
    from backend.services import container_mutator

    calls = []

    def fake_recreate(cid, approve_elevated=False, **kw):
        calls.append(approve_elevated)
        if not approve_elevated:
            raise container_mutator.ElevationNeeded(["bind /"])
        return {"status": "ok"}

    monkeypatch.setattr(container_mutator, "recreate_container", fake_recreate)
    name = _name("ha")
    user = create_user(name, "Home Assistant", "GoodPass123!", role_id="app_operator")
    raw, _ = create_scoped_api_token(user["id"], "ha", ["containers:manage"])
    body = {"binds": ["/:/host"]}
    r = client.post("/api/docker/containers/plex/recreate", json=body, headers=_bearer(raw))
    assert r.status_code == 403
    r = client.post("/api/docker/containers/plex/recreate", json=body, headers=auth_headers)
    assert r.status_code == 428 and r.json()["error"] == "confirmation_required"
    r = client.post(
        "/api/docker/containers/plex/recreate", json=body, headers={**auth_headers, "X-Confirm-Token": "zcf_x"}
    )
    assert r.status_code == 200 and calls[-1] is True


def test_docker_proxy_checks_the_paths_it_missed(data_alias):
    from backend import docker_proxy

    def reasons(hc):
        return docker_proxy.elevated_reasons("/containers/create", {"HostConfig": hc})

    assert reasons({"Binds": ["/var/run/docker.sock:/var/run/docker.sock"]})
    assert reasons({"Binds": ["/var/log:/logs"]})
    assert reasons({"Binds": [f"{data_alias}:/steal"]})
    assert reasons({"NetworkMode": "host"})
    assert not reasons({"Binds": ["/mnt/user/media:/media"]})
    vol = {"Name": "x", "Driver": "local", "DriverOpts": {"type": "none", "o": "bind", "device": "/etc"}}
    ok, _, why = docker_proxy.check_request("POST", "/volumes/create", {}, json.dumps(vol).encode())
    assert not ok and why


# ------------------------------------------------------------------ SEC-5 / REL-1 backups
class _FakeRclone:
    def __init__(self, crypt_fails=False, final="success"):
        self.crypt_fails, self.final, self.syncs = crypt_fails, final, []

    def create_crypt_remote(self, **kw):
        if self.crypt_fails:
            raise RuntimeError("crypt broken")

    def start_sync_job(self, **kw):
        self.syncs.append(kw)
        return {"id": "s1"}

    def get_sync_job(self, job_id):
        return {"status": self.final, "error": "boom", "transfer_log": []}


@pytest.fixture
def backup_source(paths, monkeypatch):
    from backend.services import backup_engine

    src = os.path.join(paths["pool"], "family")
    os.makedirs(src, exist_ok=True)

    class _Pal:
        def get_pool_path(self, pool_id):
            return paths["pool"]

        def create_snapshot(self, **kw):  # a host that doesn't do snapshots
            raise backup_engine.PlatformCapabilityError("observer mode")

    monkeypatch.setattr(backup_engine, "get_storage_platform", lambda: _Pal())
    monkeypatch.setattr(backup_engine, "prune_job_snapshots", lambda *a: [])
    monkeypatch.setattr(backup_engine, "SYNC_POLL_SECONDS", 0.01)
    yield src
    shutil.rmtree(src, ignore_errors=True)


def _job(**extra):
    from backend.services import backup_engine

    return backup_engine.save_backup_job(
        {
            "name": "Family",
            "source_subvolume": "",
            "destination_type": "remote",
            "remote_name": "cloud",
            "remote_path": "backup",
            "schedule": "manual",
            **extra,
        }
    )


def test_a_failed_encryption_setup_uploads_nothing(backup_source, monkeypatch):
    from backend.services import backup_engine

    with open(os.path.join(backup_source, "photo.jpg"), "w") as f:
        f.write("x")
    fake = _FakeRclone(crypt_fails=True)
    monkeypatch.setattr(backup_engine, "get_rclone_engine", lambda: fake)
    monkeypatch.setattr(backup_engine, "checked_subvolume", lambda s: "family")
    job = _job(encrypted=True, encryption_password="a long passphrase")
    res = backup_engine.execute_backup_job(job["id"])
    assert res["status"] == "error" and "Nothing was uploaded" in res["error"]
    assert fake.syncs == []


def test_an_empty_source_never_mirrors(backup_source, monkeypatch):
    from backend.services import backup_engine

    fake = _FakeRclone()
    monkeypatch.setattr(backup_engine, "get_rclone_engine", lambda: fake)
    monkeypatch.setattr(backup_engine, "checked_subvolume", lambda s: "family")
    res = backup_engine.execute_backup_job(_job()["id"])
    assert res["status"] == "error" and "empty" in res["error"] and fake.syncs == []


def test_success_waits_for_the_upload_and_limits_deletions(backup_source, monkeypatch):
    from backend.services import backup_engine

    with open(os.path.join(backup_source, "doc.txt"), "w") as f:
        f.write("x")
    monkeypatch.setattr(backup_engine, "checked_subvolume", lambda s: "family")
    ok = _FakeRclone()
    monkeypatch.setattr(backup_engine, "get_rclone_engine", lambda: ok)
    assert backup_engine.execute_backup_job(_job()["id"])["status"] == "success"
    flags = ok.syncs[0]["extra_flags"]
    assert flags[:2] == ["--max-delete", str(backup_engine.MAX_DELETE_PER_RUN)] and "--backup-dir" in flags  # REL-9
    failed = _FakeRclone(final="error")
    monkeypatch.setattr(backup_engine, "get_rclone_engine", lambda: failed)
    assert backup_engine.execute_backup_job(_job()["id"])["status"] == "error"


def test_a_job_never_runs_twice_at_once(backup_source):
    from backend.services import backup_engine

    job = _job()
    backup_engine._RUNNING_JOBS.add(job["id"])
    try:
        with pytest.raises(ValueError, match="already running"):
            backup_engine.execute_backup_job(job["id"])
    finally:
        backup_engine._RUNNING_JOBS.discard(job["id"])


def test_passphrases_are_stored_encrypted(backup_source):
    from backend import secret_box
    from backend.services import backup_engine

    job = _job(encrypted=True, encryption_password="a long passphrase")
    stored = next(j for j in backup_engine.get_backup_jobs() if j["id"] == job["id"])
    assert secret_box.is_sealed(stored["encryption_password"])
    assert backup_engine.job_passphrase(stored) == "a long passphrase"
    with open(backup_engine.BACKUP_JOBS_FILE) as f:
        raw = f.read()
    assert "a long passphrase" not in raw


# ------------------------------------------------------------------ AI-11 MCP
def test_file_search_over_mcp_needs_its_own_scope():
    from backend.api import mcp
    from backend.auth import AuthenticatedPrincipal

    dash = AuthenticatedPrincipal(
        {"user_id": ADMIN, "username": "admin", "role_id": "superadmin", "scopes": ["system:view"]}
    )
    names = {t["name"] for t in mcp._mcp_tools(dash)}
    assert "search_nas_knowledge" not in names
    reader = AuthenticatedPrincipal(
        {"user_id": ADMIN, "username": "admin", "role_id": "superadmin", "scopes": ["system:view", "ai:knowledge:read"]}
    )
    assert "search_nas_knowledge" in {t["name"] for t in mcp._mcp_tools(reader)}


def test_mcp_results_are_short_snippets_framed_as_file_text():
    from backend.api import mcp

    res = {
        "status": "ok",
        "citations": [
            {
                "name": "a.txt",
                "path": "/p/a.txt",
                "excerpt": "x" * 2000,
                "full_parent_context": "whole file",
                "score": 0.9,
            }
        ],
    }
    out = mcp._knowledge_snippets(res)
    assert out["note"] == mcp.UNTRUSTED_NOTE
    assert len(out["results"][0]["excerpt"]) == mcp.EXCERPT_CHARS and "full_parent_context" not in out["results"][0]


def test_mcp_refuses_other_websites(client, auth_headers):
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    r = client.post("/api/mcp", json=body, headers={**auth_headers, "Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.post("/api/mcp", json=body, headers=auth_headers).status_code == 200


# ------------------------------------------------------------------ one-time cleanup
def test_the_1_10_2_cleanup_revokes_stale_tokens_and_seals_passphrases(backup_source):
    from backend import secret_box
    from backend.services import backup_engine, security_upgrade
    from backend.users_db import users_db_session

    marker = os.path.join(config.DATA_DIR, security_upgrade.MARKER_1_10_2)
    if os.path.exists(marker):
        os.remove(marker)
    name = _name("st")
    user = create_user(name, "Demoted", "GoodPass123!", role_id="share_user")
    with users_db_session(None) as conn:  # a token from before scopes were capped
        conn.execute(
            "INSERT INTO api_tokens (token_id, user_id, name, token_hash, masked_token, scopes_json, created_at) "
            "VALUES (?, ?, 'old', ?, 'zat_...', '[\"*\"]', 0)",
            (secrets.token_hex(8), user["id"], secrets.token_hex(32)),
        )
    jobs = backup_engine.get_backup_jobs() + [{"id": "plain1", "name": "Old", "encryption_password": "plain secret"}]
    fsutil.atomic_write_json(backup_engine.BACKUP_JOBS_FILE, jobs)

    assert security_upgrade.run_1_10_2_once() is True
    with users_db_session(None) as conn:
        left = conn.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id = ?", (user["id"],)).fetchone()[0]
        role = json.loads(conn.execute("SELECT scopes_json FROM roles WHERE id='share_user'").fetchone()[0])
    assert left == 0 and "ai:knowledge:read" in role
    old = next(j for j in backup_engine.get_backup_jobs() if j["id"] == "plain1")
    assert secret_box.is_sealed(old["encryption_password"])
    assert security_upgrade.run_1_10_2_once() is False
    assert get_user_by_username(name)


# ------------------------------------------------------------------ users:write limits
def test_user_managers_cannot_hand_out_more_than_they_have(client):
    from backend.users_db import users_db_session

    with users_db_session(None) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO roles (id, name, description, scopes_json, is_system, created_at) "
            "VALUES ('helpdesk', 'Helpdesk', 'Manages family accounts', ?, 0, 0)",
            (json.dumps(["users:read", "users:write", "shares:read", "shares:user_write", "system:view"]),),
        )
    name = _name("hd")
    helper = create_user(name, "Helpdesk", "GoodPass123!", role_id="helpdesk")
    raw, _ = create_scoped_api_token(
        helper["id"], "hd", ["users:read", "users:write", "shares:read", "shares:user_write", "system:view"]
    )
    bad = {"username": _name("x"), "password": "GoodPass123!", "role_id": "superadmin"}
    assert client.post("/api/users", json=bad, headers=_bearer(raw)).status_code == 403
    ok = {"username": _name("kid"), "password": "GoodPass123!", "role_id": "kid"}
    assert client.post("/api/users", json=ok, headers=_bearer(raw)).status_code == 200
    kid = get_user_by_username(ok["username"])
    r = client.put(f"/api/users/{kid['id']}", json={"role_id": "superadmin"}, headers=_bearer(raw))
    assert r.status_code == 403
    r = client.put(f"/api/users/{ADMIN}", json={"status": "disabled"}, headers=_bearer(raw))
    assert r.status_code == 403
