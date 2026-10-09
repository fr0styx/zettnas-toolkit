import json
import os
import subprocess
import sys
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

import backend.config as config
from backend.main import app
from backend.users_db import init_users_db, create_user, get_user_by_username
from backend.auth import (
    create_session,
    validate_session,
    get_current_session,
)
from backend.api.auth import create_stream_ticket, validate_and_consume_stream_ticket


@pytest.fixture(autouse=True)
def setup_phase4_env(monkeypatch, tmp_path):
    orig_db = config.USERS_DB_PATH
    orig_roots = config.ALLOWED_BROWSE_ROOTS
    orig_pool = config.POOL_PATH

    temp_db = str(tmp_path / "test_users_p4.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", temp_db)
    init_users_db(temp_db)

    # Setup temporary browsable directory structure
    pool_root = str(tmp_path / "pool")
    homes_dir = os.path.join(pool_root, "homes")
    alice_home = os.path.join(homes_dir, "alice")
    bob_home = os.path.join(homes_dir, "bob")
    os.makedirs(alice_home, exist_ok=True)
    os.makedirs(bob_home, exist_ok=True)

    with open(os.path.join(alice_home, "alice_notes.txt"), "w") as f:
        f.write("Alice private data")
    with open(os.path.join(bob_home, "bob_secrets.txt"), "w") as f:
        f.write("Bob private data")

    import backend.api.system as system_api

    monkeypatch.setattr(config, "POOL_PATH", pool_root)
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", (pool_root,))
    monkeypatch.setattr(system_api, "ALLOWED_BROWSE_ROOTS", (pool_root,))

    yield {
        "pool_root": pool_root,
        "homes_dir": homes_dir,
        "alice_home": alice_home,
        "bob_home": bob_home,
    }

    config.USERS_DB_PATH = orig_db
    config.ALLOWED_BROWSE_ROOTS = orig_roots
    config.POOL_PATH = orig_pool


def test_stream_ticket_lifecycle():
    """Verify single-use, 60-second stream tickets for SSE/WebSocket endpoints."""
    ticket = create_stream_ticket(
        user_id="user-123",
        username="alice",
        scopes=["system:view", "storage:read"],
        role_id="share_user",
    )
    assert ticket.startswith("zst_")

    # 1. Validation works on first use
    assert validate_session(ticket) is True
    session_data = get_current_session(ticket)
    assert session_data is not None
    assert session_data["username"] == "alice"
    assert session_data["role_id"] == "share_user"
    assert "storage:read" in session_data["scopes"]

    # 2. Ticket is single-use: subsequent check must fail
    second_attempt = validate_and_consume_stream_ticket(ticket)
    assert second_attempt is None


def test_home_folder_isolation_and_browse(setup_phase4_env):
    """Verify standard users cannot access other users' homes, but admins can."""
    env = setup_phase4_env
    # Create alice and bob in users.db
    create_user("alice", "Alice User", "AlicePass123!", role_id="share_user")
    create_user("bob", "Bob User", "BobPass123!", role_id="share_user")
    create_user("admin_user", "Admin User", "AdminPass123!", role_id="superadmin")

    client = TestClient(app)

    # Login as alice
    login_alice = client.post("/api/auth/login", json={"username": "alice", "password": "AlicePass123!"})
    assert login_alice.status_code == 200
    token_alice = login_alice.json().get("token") or login_alice.cookies.get("zettnas_session")
    headers_alice = {"Authorization": f"Bearer {token_alice}"}

    # 1. Alice can browse her own home folder
    r_alice_own = client.get(f"/api/browse?path={env['alice_home']}", headers=headers_alice)
    assert r_alice_own.status_code == 200
    names = [d["name"] for d in r_alice_own.json()["dirs"]]
    assert "alice_notes.txt" in names

    # 2. Alice CANNOT browse Bob's home folder (403 Forbidden)
    r_alice_bob = client.get(f"/api/browse?path={env['bob_home']}", headers=headers_alice)
    assert r_alice_bob.status_code == 403

    # 3. Alice CANNOT mkdir in Bob's home folder
    r_mkdir_bob = client.post(
        "/api/mkdir", json={"path": os.path.join(env["bob_home"], "hacked")}, headers=headers_alice
    )
    assert r_mkdir_bob.status_code == 403

    # 4. Alice CAN mkdir in her own home folder
    r_mkdir_own = client.post(
        "/api/mkdir", json={"path": os.path.join(env["alice_home"], "projects")}, headers=headers_alice
    )
    assert r_mkdir_own.status_code == 200

    # 5. Alice browsing /homes directory only sees her own directory
    r_homes = client.get(f"/api/browse?path={env['homes_dir']}", headers=headers_alice)
    assert r_homes.status_code == 200
    homes_entries = [d["name"] for d in r_homes.json()["dirs"] if d["name"] != ".."]
    assert "alice" in homes_entries
    assert "bob" not in homes_entries

    # 6. Admin can browse both homes and see all entries
    login_admin = client.post("/api/auth/login", json={"username": "admin_user", "password": "AdminPass123!"})
    token_admin = login_admin.json().get("token") or login_admin.cookies.get("zettnas_session")
    headers_admin = {"Authorization": f"Bearer {token_admin}"}

    r_admin_homes = client.get(f"/api/browse?path={env['homes_dir']}", headers=headers_admin)
    assert r_admin_homes.status_code == 200
    admin_homes_entries = [d["name"] for d in r_admin_homes.json()["dirs"] if d["name"] != ".."]
    assert "alice" in admin_homes_entries
    assert "bob" in admin_homes_entries


def test_rclone_auth_proxy_script(setup_phase4_env):
    """Verify rclone_auth_proxy.py correctly outputs JSON config for rclone STDIN."""
    create_user("alice", "Alice User", "AlicePass123!", role_id="share_user")
    create_user("admin_user", "Admin User", "AdminPass123!", role_id="superadmin")

    script_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "backend", "services", "rclone_auth_proxy.py"
    )

    # 1. Test Alice (standard user) -> isolated home directory root
    proc_alice = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps({"user": "alice", "pass": "AlicePass123!"}),
        text=True,
        capture_output=True,
        env={**os.environ, "USERS_DB_PATH": config.USERS_DB_PATH, "POOL_PATH": config.POOL_PATH},
    )
    assert proc_alice.returncode == 0
    resp_alice = json.loads(proc_alice.stdout)
    assert resp_alice["type"] == "local"
    assert resp_alice["_root"].endswith(os.path.join("homes", "alice"))

    # 2. Test Admin (superadmin) -> full pool root
    proc_admin = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps({"user": "admin_user", "pass": "AdminPass123!"}),
        text=True,
        capture_output=True,
        env={**os.environ, "USERS_DB_PATH": config.USERS_DB_PATH, "POOL_PATH": config.POOL_PATH},
    )
    assert proc_admin.returncode == 0
    resp_admin = json.loads(proc_admin.stdout)
    assert resp_admin["type"] == "local"
    assert resp_admin["_root"] == config.POOL_PATH

    # 3. Test Invalid Password -> Exit code 1
    proc_invalid = subprocess.run(
        [sys.executable, script_path],
        input=json.dumps({"user": "alice", "pass": "WrongPassword!"}),
        text=True,
        capture_output=True,
        env={**os.environ, "USERS_DB_PATH": config.USERS_DB_PATH, "POOL_PATH": config.POOL_PATH},
    )
    assert proc_invalid.returncode != 0


def test_webdav_portal_multiuser_login(setup_phase4_env):
    """Verify WebDAV web portal authenticates multi-user credentials."""
    create_user("alice", "Alice User", "AlicePass123!", role_id="share_user")
    client = TestClient(app)

    # Valid user login
    resp_ok = client.post(
        "/webdav/auth/login",
        data={"username": "alice", "password": "AlicePass123!"},
        follow_redirects=False,
    )
    assert resp_ok.status_code == 303
    cookie = resp_ok.cookies.get("webdav_session")
    assert cookie is not None
    assert cookie.startswith("alice:")

    # Invalid user login
    resp_bad = client.post(
        "/webdav/auth/login",
        data={"username": "alice", "password": "WrongPassword!"},
        follow_redirects=False,
    )
    assert resp_bad.status_code == 200
    assert "Invalid WebDAV" in resp_bad.text


def test_webdav_portal_serves_files_directly_without_basic_auth(setup_phase4_env):
    """Verify WebDAV web portal serves files directly via FileResponse with no 401 Basic Auth dialogs."""
    env = setup_phase4_env
    create_user("alice", "Alice User", "AlicePass123!", role_id="share_user")

    # Create test image file and AppleDouble sidecar file
    test_img = os.path.join(env["alice_home"], "._DSCF9385.JPG")
    with open(test_img, "wb") as f:
        f.write(b"\x00\x05\x16\x07Mac OS X metadata")

    client = TestClient(app)

    # 1. Login to WebDAV portal as Alice
    resp_login = client.post(
        "/webdav/auth/login",
        data={"username": "alice", "password": "AlicePass123!"},
        follow_redirects=False,
    )
    assert resp_login.status_code == 303
    webdav_cookie = resp_login.cookies.get("webdav_session")
    assert webdav_cookie is not None

    cookies = {"webdav_session": webdav_cookie}

    # 2. Browse directory: returns 200 HTML portal with file links
    resp_browse = client.get("/webdav/", cookies=cookies)
    assert resp_browse.status_code == 200
    assert "text/html" in resp_browse.headers.get("content-type", "")
    assert "alice_notes.txt" in resp_browse.text
    assert "._DSCF9385.JPG" in resp_browse.text

    # 3. Click file name: serves file directly (inline) with 200 OK and NO 401 Basic Auth challenge!
    resp_file = client.get("/webdav/alice_notes.txt", cookies=cookies)
    assert resp_file.status_code == 200
    assert resp_file.text == "Alice private data"
    assert "www-authenticate" not in resp_file.headers
    assert resp_file.headers.get("content-disposition", "") == "inline; filename=\"alice_notes.txt\""

    # 4. Click AppleDouble sidecar JPG file: serves file directly without 401 prompt
    resp_jpg = client.get("/webdav/._DSCF9385.JPG", cookies=cookies)
    assert resp_jpg.status_code == 200
    assert resp_jpg.content == b"\x00\x05\x16\x07Mac OS X metadata"
    assert "www-authenticate" not in resp_jpg.headers

    # 5. Click "⬇️ Download" button (?raw=1): serves as attachment
    resp_download = client.get("/webdav/alice_notes.txt?raw=1", cookies=cookies)
    assert resp_download.status_code == 200
    assert "attachment" in resp_download.headers.get("content-disposition", "")
    assert resp_download.text == "Alice private data"
    assert "www-authenticate" not in resp_download.headers


def test_webdav_portal_desktop_sso_and_unauth_fallback(setup_phase4_env):
    """Verify Desktop session SSO in WebDAV portal and friendly login page on unauthenticated access."""
    create_user("admin_user", "Admin User", "AdminPass123!", role_id="superadmin")
    client = TestClient(app)

    # 1. Unauthenticated browser access returns 200 with HTML login page, NOT 401 Basic Auth prompt!
    resp_unauth = client.get("/webdav/")
    assert resp_unauth.status_code == 200
    assert "text/html" in resp_unauth.headers.get("content-type", "")
    assert "Sign In" in resp_unauth.text
    assert "www-authenticate" not in resp_unauth.headers

    # 2. Login to ZettNAS Workbench Desktop (sets zettnas_session cookie)
    resp_login = client.post(
        "/api/auth/login",
        json={"username": "admin_user", "password": "AdminPass123!"},
    )
    assert resp_login.status_code == 200
    desktop_token = resp_login.json().get("token") or resp_login.cookies.get("zettnas_session")

    # 3. Access WebDAV portal with desktop cookie -> SSO automatically authenticates!
    resp_sso = client.get("/webdav/", cookies={"zettnas_session": desktop_token})
    assert resp_sso.status_code == 200
    assert "ZettNAS WebDAV" in resp_sso.text
    assert "admin_user" in resp_sso.text

