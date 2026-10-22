"""
Unit and Integration Tests for v1.9.0 Consumer-Grade Differentiators (Batch 7):
1. Security Posture Evaluation & Setup Wizard Enforcements
2. Interactive Docker Terminal WebSocket Authentication
3. Multi-Container Catalog Compose Synthesizer
4. Client-Side rclone crypt Remote Provisioning
5. Scrutiny-Style S.M.A.R.T. Velocity & Scheduled Test Runner
"""

import configparser
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from backend.db import init_db, query_smart_velocity
from backend.services.app_catalog import generate_compose_for_app
from backend.services.rclone_engine import RcloneEngine
from backend.services.scheduler import (
    get_smart_schedule,
    save_smart_schedule,
)
from backend.services.security_advisor import evaluate_security_posture
from backend.users_db import hash_password, verify_password


class MockCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class MockConn:
    def __init__(self, mfa=0, tokens=None):
        self.mfa = mfa
        self.tokens = tokens or []

    def execute(self, query, *args):
        if "users" in query:
            return MockCursor([{"id": "usr_1", "username": "admin", "mfa_enabled": self.mfa}])
        if "api_tokens" in query:
            return MockCursor(self.tokens)
        return MockCursor([])


@contextmanager
def mock_session_no_mfa():
    yield MockConn(mfa=0)


@contextmanager
def mock_session_with_mfa():
    yield MockConn(mfa=1)


def test_password_hash_verification_not_raw_equality():
    """Confirms Argon2id hashed passwords match via verify_password and never direct equality."""
    h1 = hash_password("admin")
    h2 = hash_password("admin")
    # Salting makes identical passwords produce different hashes
    assert h1 != h2
    assert verify_password("admin", h1) is True
    assert verify_password("admin", h2) is True
    assert verify_password("wrong", h1) is False


def test_security_posture_evaluation_default_password():
    """Security posture advisor assigns failing grade when default credentials exist."""
    mock_samba = MagicMock()
    mock_share = MagicMock()
    mock_share.guest_ok = True
    mock_share.name = "public_share"
    mock_samba.list_shares.return_value = [mock_share]

    with (
        patch("backend.services.security_advisor.is_using_default_password", return_value=True),
        patch("backend.services.security_advisor.users_db_session", side_effect=mock_session_no_mfa),
        patch("backend.services.samba_engine.get_samba_engine", return_value=mock_samba),
    ):
        posture = evaluate_security_posture()
        assert posture["score"] <= 60
        assert posture["grade"] in ("D", "F")
        checks = {c["id"]: c for c in posture["checks"]}
        assert checks["default_password"]["passed"] is False
        assert checks["smb_guest_access"]["passed"] is False


def test_security_posture_evaluation_hardened():
    """Security posture advisor assigns top score when all security defenses are active."""
    mock_samba = MagicMock()
    mock_share = MagicMock()
    mock_share.guest_ok = False
    mock_share.name = "secure_vault"
    mock_samba.list_shares.return_value = [mock_share]

    with (
        patch("backend.services.security_advisor.is_using_default_password", return_value=False),
        patch("backend.services.security_advisor.users_db_session", side_effect=mock_session_with_mfa),
        patch("backend.services.samba_engine.get_samba_engine", return_value=mock_samba),
        patch.dict("os.environ", {"ENABLE_PROXY_SSO": "1", "TRUSTED_PROXIES": "10.0.0.1"}),
    ):
        posture = evaluate_security_posture()
        assert posture["score"] >= 85
        assert posture["grade"] in ("A", "B")
        checks = {c["id"]: c for c in posture["checks"]}
        assert checks["default_password"]["passed"] is True
        assert checks["admin_mfa"]["passed"] is True
        assert checks["smb_guest_access"]["passed"] is True


def test_app_catalog_multi_container_compose():
    """Catalog compose generator synthesizes dependencies, environment, and volume overrides."""
    env_overrides = {"MYSQL_PASSWORD": "usersecret123"}
    volume_overrides = {"/var/www/html": "/mnt/user/appdata/nextcloud"}
    stack_services = {
        "db": {
            "image": "mariadb:10.11",
            "restart": "unless-stopped",
            "env": {"MYSQL_ROOT_PASSWORD": "rootpassword"},
            "volumes": {"data": "/var/lib/mysql"},
        },
        "redis": {
            "image": "redis:alpine",
            "restart": "unless-stopped",
        },
    }

    res = generate_compose_for_app(
        "nextcloud",
        env_overrides=env_overrides,
        volume_overrides=volume_overrides,
        stack_services=stack_services,
    )

    assert "compose_yaml" in res
    compose_yaml = res["compose_yaml"]

    assert "nextcloud:" in compose_yaml
    assert "image:" in compose_yaml
    assert "depends_on:" in compose_yaml
    assert "db" in compose_yaml
    assert "redis" in compose_yaml
    assert "mariadb:10.11" in compose_yaml
    assert "redis:alpine" in compose_yaml


def test_rclone_crypt_remote_creation(tmp_path):
    """Client-side rclone crypt remote generator constructs valid encrypted overlay."""
    engine = RcloneEngine()
    engine.config_file = str(tmp_path / "rclone.conf")

    with patch.object(engine, "_obscure_password", side_effect=lambda p: f"obscured_{p}"):
        remote = engine.create_crypt_remote(
            name="crypt-backup",
            base_remote_path="gdrive:secure_vault",
            password="pass1",
            password2="salt2",
            filename_encryption="standard",
            directory_name_encryption=True,
        )

        assert remote["name"] == "crypt-backup"
        assert remote["type"] == "crypt"

        cfg = configparser.RawConfigParser()
        cfg.read(engine.config_file)
        assert cfg.has_section("crypt-backup")
        assert cfg.get("crypt-backup", "type") == "crypt"
        assert cfg.get("crypt-backup", "remote") == "gdrive:secure_vault"
        assert cfg.get("crypt-backup", "password") == "obscured_pass1"
        assert cfg.get("crypt-backup", "password2") == "obscured_salt2"


def test_smart_scheduler_configuration(tmp_path, monkeypatch):
    """SMART test scheduler manages configuration persistence while preserving spindown safety."""
    test_sched_file = str(tmp_path / "smart_sched.json")
    monkeypatch.setattr("backend.services.scheduler.SMART_SCHEDULE_FILE", test_sched_file)

    initial = get_smart_schedule()
    assert initial["enabled"] is True
    assert initial["skip_if_standby"] is True

    updated = save_smart_schedule(
        {
            "enabled": True,
            "short_test_interval": "weekly",
            "short_test_day": 3,
            "short_test_hour": 4,
            "extended_test_interval": "monthly",
            "extended_test_day": 20,
            "extended_test_hour": 1,
            "skip_if_standby": True,
        }
    )

    assert updated["short_test_interval"] == "weekly"
    assert updated["short_test_day"] == 3
    assert updated["short_test_hour"] == 4
    assert updated["extended_test_day"] == 20
    assert updated["skip_if_standby"] is True

    reloaded = get_smart_schedule()
    assert reloaded["short_test_interval"] == "weekly"
    assert reloaded["short_test_day"] == 3


def test_smart_velocity_and_scrutiny_failure_predictions(tmp_path, monkeypatch):
    """Scrutiny failure risk telemetry calculates failure probability and historical attributes."""
    test_db = str(tmp_path / "test_history.db")
    monkeypatch.setattr("backend.db.DB_PATH", test_db)
    init_db()

    v = query_smart_velocity("sda")
    assert v["dev"] == "sda"
    assert "failure_probability" in v
    assert 0.0 <= v["failure_probability"] <= 1.0
    assert v["failure_risk"] in ("low", "moderate", "high", "critical")
    assert "key_attributes" in v
    assert "reallocated_sectors" in v["key_attributes"]
    assert "pending_sectors" in v["key_attributes"]


def test_api_security_posture_endpoint(client, token):
    """GET /api/system/security-posture returns structured security posture."""
    res = client.get("/api/system/security-posture", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "score" in data
    assert "grade" in data
    assert "checks" in data
    assert isinstance(data["checks"], list)


def test_api_smart_schedule_endpoints(client, token):
    """GET and POST /api/storage/smart/schedule update and fetch SMART configuration."""
    res_get = client.get("/api/storage/smart/schedule", headers={"Authorization": f"Bearer {token}"})
    assert res_get.status_code == 200
    sched = res_get.json()
    assert "enabled" in sched
    assert "skip_if_standby" in sched

    res_post = client.post(
        "/api/storage/smart/schedule",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "enabled": True,
            "short_test_interval": "weekly",
            "short_test_day": 5,
            "short_test_hour": 3,
        },
    )
    assert res_post.status_code == 200
    updated = res_post.json()
    assert updated["short_test_interval"] == "weekly"
    assert updated["short_test_day"] == 5
    assert updated["short_test_hour"] == 3


def test_api_smart_failure_predictions_endpoint(client, token):
    """GET /api/storage/smart/failure-predictions returns list of drives with Scrutiny telemetry."""
    res = client.get("/api/storage/smart/failure-predictions", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    drives = res.json()
    assert isinstance(drives, list)
    for d in drives:
        assert "failure_probability" in d
        assert "failure_risk" in d
        assert "key_attributes" in d
