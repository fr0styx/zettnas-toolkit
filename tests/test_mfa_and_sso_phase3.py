import json
import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.main import app
from backend.totp import (
    generate_totp_secret,
    generate_totp_code,
    verify_totp_code,
    generate_recovery_codes,
    hash_recovery_code,
    verify_and_consume_recovery_code,
    generate_qr_svg,
    get_otpauth_uri,
)
from backend.users_db import (
    init_users_db,
    create_user,
    get_user_by_username,
    get_user_mfa,
    enable_user_mfa,
    disable_user_mfa,
)


@pytest.fixture
def test_env():
    """Sets up a temporary SQLite users database and test client."""
    old_db_path = getattr(config, "USERS_DB_PATH", None)
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_users.db")
        config.USERS_DB_PATH = db_path
        init_users_db(db_path)

        client = TestClient(app)
        try:
            yield {"client": client, "db_path": db_path}
        finally:
            if old_db_path:
                config.USERS_DB_PATH = old_db_path


def test_totp_core_generation_and_drift():
    secret = generate_totp_secret()
    assert len(secret) >= 32

    # Current code
    code = generate_totp_code(secret)
    assert len(code) == 6
    assert code.isdigit()
    assert verify_totp_code(secret, code)

    # Drift tolerance (-1 step = -30 seconds) on a fresh secret
    secret_past = generate_totp_secret()
    now = time.time()
    past_code = generate_totp_code(secret_past, for_time=now - 30)
    assert verify_totp_code(secret_past, past_code)

    # Drift tolerance (+1 step = +30 seconds) on a fresh secret
    secret_future = generate_totp_secret()
    future_code = generate_totp_code(secret_future, for_time=now + 30)
    assert verify_totp_code(secret_future, future_code)

    # Beyond drift window (e.g. 90 seconds in the past)
    old_code = generate_totp_code(secret, for_time=now - 90)
    assert not verify_totp_code(secret, old_code)


def test_totp_anti_replay_protection():
    secret = generate_totp_secret()
    code = generate_totp_code(secret)
    user_id = "test-replay-user-01"

    # First verification succeeds
    assert verify_totp_code(secret, code, user_id=user_id)

    # Replay of the exact same timestep code fails
    assert not verify_totp_code(secret, code, user_id=user_id)


def test_recovery_codes_hashing_and_single_use():
    codes = generate_recovery_codes(8)
    assert len(codes) == 8
    for c in codes:
        assert "-" in c
        assert len(c) == 9

    hashes = [hash_recovery_code(c) for c in codes]
    first_code = codes[0]

    # Verify and consume first code
    ok, updated = verify_and_consume_recovery_code(hashes, first_code)
    assert ok
    assert len(updated) == 7

    # Attempting to reuse consumed code fails
    ok2, updated2 = verify_and_consume_recovery_code(updated, first_code)
    assert not ok2
    assert len(updated2) == 7


def test_qr_svg_generation():
    uri = get_otpauth_uri("testuser", "JBSWY3DPEHPK3PXP", issuer="ZettNAS")
    svg = generate_qr_svg(uri)
    assert "<svg" in svg
    assert "</svg>" in svg
    assert "viewBox" in svg
    assert "path" in svg


def test_mfa_setup_enable_and_status_api(test_env):
    client = test_env["client"]

    # 1. Login as admin
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Check initial MFA status
    status_res = client.get("/api/auth/mfa/status", headers=headers)
    assert status_res.status_code == 200
    assert status_res.json()["mfa_enabled"] is False

    # 3. Request MFA setup
    setup_res = client.post("/api/auth/mfa/setup", headers=headers)
    assert setup_res.status_code == 200
    setup_data = setup_res.json()
    assert "secret" in setup_data
    assert "otpauth_uri" in setup_data
    assert "qr_svg" in setup_data
    assert len(setup_data["recovery_codes"]) == 8

    secret = setup_data["secret"]
    recovery_codes = setup_data["recovery_codes"]

    # 4. Attempt enable with invalid code
    bad_res = client.post(
        "/api/auth/mfa/enable",
        headers=headers,
        json={"secret": secret, "code": "000000", "recovery_codes": recovery_codes},
    )
    assert bad_res.status_code == 400

    # 5. Enable with valid code
    valid_code = generate_totp_code(secret)
    enable_res = client.post(
        "/api/auth/mfa/enable",
        headers=headers,
        json={"secret": secret, "code": valid_code, "recovery_codes": recovery_codes},
    )
    assert enable_res.status_code == 200
    assert enable_res.json()["status"] == "ok"

    # 6. Verify status updated
    status_res2 = client.get("/api/auth/mfa/status", headers=headers)
    assert status_res2.status_code == 200
    assert status_res2.json()["mfa_enabled"] is True
    assert status_res2.json()["recovery_codes_count"] == 8


def test_mfa_login_challenge_flow(test_env):
    client = test_env["client"]

    # 1. Create a dedicated user with MFA pre-enabled
    secret = generate_totp_secret()
    recovery_codes = generate_recovery_codes(8)
    hashes = [hash_recovery_code(c) for c in recovery_codes]

    user = create_user(
        username="mfa_user",
        display_name="MFA Test User",
        password="ValidPassword123!",
        role_id="share_user",
        db_path=test_env["db_path"],
    )
    enable_user_mfa(user["id"], secret, hashes, db_path=test_env["db_path"])

    # 2. Login without code -> expects mfa_required with mfa_token
    res = client.post("/api/auth/login", json={"username": "mfa_user", "password": "ValidPassword123!"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "mfa_required"
    assert "mfa_token" in data
    mfa_token = data["mfa_token"]

    # 3. Complete challenge with invalid code
    bad_res = client.post(
        "/api/auth/mfa/challenge",
        json={"mfa_token": mfa_token, "mfa_code": "999999"},
    )
    assert bad_res.status_code == 401

    # 4. Complete challenge with valid code
    valid_code = generate_totp_code(secret)
    good_res = client.post(
        "/api/auth/mfa/challenge",
        json={"mfa_token": mfa_token, "mfa_code": valid_code},
    )
    assert good_res.status_code == 200
    session_data = good_res.json()
    assert session_data["status"] == "ok"
    assert "token" in session_data
    assert session_data["user"]["username"] == "mfa_user"
    assert session_data["user"]["mfa_enabled"] is True

    # 5. Direct login supplying mfa_code with credentials (using separate user to respect anti-replay cache)
    user2 = create_user(
        username="direct_mfa_user",
        display_name="Direct MFA User",
        password="ValidPassword123!",
        role_id="share_user",
        db_path=test_env["db_path"],
    )
    secret2 = generate_totp_secret()
    enable_user_mfa(user2["id"], secret2, hashes, db_path=test_env["db_path"])

    direct_code = generate_totp_code(secret2)
    direct_res = client.post(
        "/api/auth/login",
        json={"username": "direct_mfa_user", "password": "ValidPassword123!", "mfa_code": direct_code},
    )
    assert direct_res.status_code == 200
    assert direct_res.json()["status"] == "ok"


def test_mfa_recovery_code_login_and_disable(test_env):
    client = test_env["client"]

    # 1. Create user with MFA
    secret = generate_totp_secret()
    recovery_codes = generate_recovery_codes(8)
    hashes = [hash_recovery_code(c) for c in recovery_codes]

    user = create_user(
        username="recovery_user",
        display_name="Recovery User",
        password="SecurePassword456!",
        role_id="share_user",
        db_path=test_env["db_path"],
    )
    enable_user_mfa(user["id"], secret, hashes, db_path=test_env["db_path"])

    # 2. Login -> get mfa_token
    step1 = client.post("/api/auth/login", json={"username": "recovery_user", "password": "SecurePassword456!"})
    mfa_tok = step1.json()["mfa_token"]

    # 3. Use single-use recovery code
    used_code = recovery_codes[0]
    step2 = client.post(
        "/api/auth/mfa/challenge",
        json={"mfa_token": mfa_tok, "recovery_code": used_code},
    )
    assert step2.status_code == 200
    token = step2.json()["token"]

    # 4. Check status shows 7 codes left
    headers = {"Authorization": f"Bearer {token}"}
    status = client.get("/api/auth/mfa/status", headers=headers).json()
    assert status["recovery_codes_count"] == 7

    # 5. Disable MFA using password
    disable_res = client.post(
        "/api/auth/mfa/disable",
        headers=headers,
        json={"password": "SecurePassword456!"},
    )
    assert disable_res.status_code == 200

    # 6. Verify subsequent login succeeds directly without MFA challenge
    direct = client.post("/api/auth/login", json={"username": "recovery_user", "password": "SecurePassword456!"})
    assert direct.status_code == 200
    assert direct.json()["status"] == "ok"


def test_reverse_proxy_sso_authentication(test_env):
    client = test_env["client"]

    # Enable Proxy SSO
    config.ENABLE_PROXY_SSO = True
    config.TRUSTED_PROXIES = ["testclient", "127.0.0.1", "10.0.0.0/8"]

    try:
        # Request with X-Forwarded-User header from trusted client (TestClient default is testclient/127.0.0.1)
        headers = {
            "X-Forwarded-User": "authentik_alex",
            "X-Forwarded-Email": "alex@enterprise.corp",
            "Remote-Name": "Alex DevOps",
        }
        res = client.get("/api/auth/me", headers=headers)
        assert res.status_code == 200
        user_info = res.json()
        assert user_info["username"] == "authentik_alex"
        assert user_info["email"] == "alex@enterprise.corp"
        assert user_info["idp_type"] == "proxy_sso"
        assert user_info["role"] == "share_user"

    finally:
        config.ENABLE_PROXY_SSO = False
