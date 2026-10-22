import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.users_db import (
    create_user,
    delete_user,
    disable_admin_user,
    get_user_by_username,
    init_users_db,
    update_user_profile,
)


def test_admin_guardrail_and_advisor(tmp_path):
    db_file = str(tmp_path / "test_users.db")
    init_users_db(db_file)

    # Initially, 'admin' is the only active superadmin in db
    admin = get_user_by_username("admin", db_path=db_file)
    assert admin is not None
    assert admin["role_id"] == "superadmin"
    assert admin["status"] == "active"

    # 1. Attempting to disable the only active superadmin must raise ValueError
    with pytest.raises(ValueError, match="Cannot disable the only active SuperAdmin"):
        update_user_profile(admin["id"], status="disabled", db_path=db_file)

    # 2. Attempting to demote the only active superadmin must raise ValueError
    with pytest.raises(ValueError, match="Cannot demote the only active SuperAdmin"):
        update_user_profile(admin["id"], role_id="share_user", db_path=db_file)

    # 3. Attempting to delete the only active superadmin must raise ValueError
    with pytest.raises(ValueError, match="Cannot delete the only active SuperAdmin"):
        delete_user(admin["id"], db_path=db_file)

    # 4. Attempting to call disable_admin_user without a second active superadmin must raise ValueError
    with pytest.raises(ValueError, match="Cannot disable the only active SuperAdmin"):
        disable_admin_user("admin", db_path=db_file)

    # 5. Create a second active SuperAdmin: 'sec_admin'
    sec_admin = create_user(
        username="sec_admin",
        display_name="Secondary Admin",
        password="SuperSecurePassword123!",
        role_id="superadmin",
        db_path=db_file,
    )
    assert sec_admin["username"] == "sec_admin"

    # 6. Now disable_admin_user must succeed!
    res = disable_admin_user("admin", db_path=db_file)
    assert res["status"] == "ok"
    assert res["disabled"] is True

    # Verify admin status is now disabled in DB
    updated_admin = get_user_by_username("admin", db_path=db_file)
    assert updated_admin["status"] == "disabled"

    # 7. Now sec_admin is the ONLY active superadmin, so sec_admin CANNOT be disabled or deleted!
    with pytest.raises(ValueError, match="Cannot disable the only active SuperAdmin"):
        update_user_profile(sec_admin["id"], status="disabled", db_path=db_file)


def test_security_advisor_api(client, auth_headers):
    # Test GET /api/security/advisor
    res = client.get("/api/security/advisor", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "score" in data
    assert "verdict" in data
    assert "checks" in data
    check_ids = [c["id"] for c in data["checks"]]
    assert "sec_default_admin" in check_ids
    assert "sec_default_password" in check_ids
    assert "sec_superadmin_mfa" in check_ids
    assert "sec_superadmin_redundancy" in check_ids
