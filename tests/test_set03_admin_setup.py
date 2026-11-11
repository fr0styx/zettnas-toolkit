"""SET-03, the owner's decision S9: an administrator's set-up is read by administrators only.

A family member could read the security check, the blocked addresses, who has no two-step sign-in,
the malware quarantine, the whole alert set-up and the diagnostics summary; so could the Viewer
role and any token made with it.
"""

import pytest

from backend.users_db import create_user, get_user_by_username

ADMIN_READS = (
    "/api/security/advisor",
    "/api/security/ransomware",
    "/api/security/ip-blocks",
    "/api/security/mfa-policy",
    "/api/security/malware-scan",
    "/api/notifications/config",
    "/api/notifications/frigate",
    "/api/system/diagnostics-summary",
)


def _login(client, name, role):
    if not get_user_by_username(name):
        create_user(name, name, "GoodPass123!", role_id=role)
    res = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.mark.parametrize("role", ["share_user", "auditor", "storage_admin", "kid"])
def test_other_roles_are_refused(client, role):
    headers = _login(client, f"adm_{role}", role)
    for path in ADMIN_READS:
        assert client.get(path, headers=headers).status_code == 403, path


def test_an_administrator_reads_them(client, auth_headers):
    for path in ADMIN_READS:
        assert client.get(path, headers=auth_headers).status_code == 200, path


def test_a_persons_own_alerts_stay_theirs(client):
    headers = _login(client, "adm_share_user", "share_user")
    assert client.get("/api/notifications/notifications/me", headers=headers).status_code == 200
