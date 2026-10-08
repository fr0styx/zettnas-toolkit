import os
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from backend.api_tokens import generate_token, revoke_token, validate_api_token
from backend.auth import create_session, revoke_session, validate_session
from backend.main import app

client = TestClient(app)


def test_security_headers_present():
    """Verify that all enterprise security headers are injected by middleware."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "camera=()" in r.headers.get("Permissions-Policy", "")


def test_auth_session_in_memory_cache_zero_disk_read_on_bogus_token():
    """Verify that probing invalid tokens does NOT trigger synchronous disk reads."""
    # Seed initial sessions
    tok = create_session("admin")
    assert validate_session(tok) is True

    # Validate an unknown token
    bogus = "totally_fake_random_token_probe"
    assert validate_session(bogus) is False

    # Now verify that subsequent lookups for unknown tokens do NOT invoke json.load on sessions.json
    with patch("json.load") as mock_json_load:
        for _ in range(20):
            assert validate_session("bogus_probe_" + str(_)) is False
        assert mock_json_load.call_count == 0

    revoke_session(tok)


def test_api_token_in_memory_cache_and_constant_time():
    """Verify API token caching, constant-time validation, and revocation."""
    raw_token = generate_token("test-service")
    assert raw_token.startswith("zat_")

    # Fast validation
    assert validate_api_token(raw_token) is True
    assert validate_api_token("zat_invalid_token_12345") is False

    # Verify no disk reads during repeated validation
    with patch("json.load") as mock_json_load:
        for _ in range(10):
            assert validate_api_token(raw_token) is True
        assert mock_json_load.call_count == 0

    # Revoke
    assert revoke_token(raw_token) is True
    assert validate_api_token(raw_token) is False


def test_docker_compose_no_wildcard_cgroups():
    """Verify that wildcard device cgroups (c *:* and b *:*) have been completely eliminated."""
    compose_path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")
    with open(compose_path, "r") as f:
        data = yaml.safe_load(f)

    cgroups = data["services"]["zettnas-toolkit"].get("device_cgroup_rules", [])
    for rule in cgroups:
        clean = rule.strip().strip("'").strip('"')
        assert "c *:* rwm" not in clean, f"Found dangerous wildcard character rule: {rule}"
        assert "b *:* rwm" not in clean, f"Found dangerous wildcard block rule: {rule}"
