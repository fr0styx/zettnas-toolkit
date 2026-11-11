"""SET-14: the security check is one list; the two account rows of the old route are in it and cost no points."""

from unittest.mock import patch

from backend.services import security_advisor


def _rows(users):
    with patch("backend.users_db.list_users", return_value=users):
        out = security_advisor.evaluate_security_posture(None)
    return {c["id"]: c for c in out["checks"]}, out


def test_admin_still_on_is_a_suggestion_without_points():
    users = [{"username": "admin", "status": "active", "role_id": "superadmin"}]
    rows, out = _rows(users)
    assert rows["sec_default_admin"]["passed"] is False
    assert rows["sec_default_admin"]["penalty"] == 0
    assert rows["sec_superadmin_redundancy"]["passed"] is False
    assert rows["sec_superadmin_redundancy"]["params"] == {"count": 1}
    assert not any(i["id"].startswith("sec-issue-sec_") for i in out["issues"])


def test_admin_off_and_two_owners_pass():
    users = [
        {"username": "admin", "status": "disabled", "role_id": "superadmin"},
        {"username": "ana", "status": "active", "role_id": "superadmin"},
        {"username": "ben", "status": "active", "role_id": "superadmin"},
    ]
    rows, _ = _rows(users)
    assert rows["sec_default_admin"]["passed"] is True
    assert rows["sec_superadmin_redundancy"]["passed"] is True


def test_the_score_does_not_move():
    users = [{"username": "admin", "status": "active", "role_id": "superadmin"}]
    _, with_rows = _rows(users)
    with patch.object(security_advisor, "_check_admin_accounts", lambda checks: None):
        without = security_advisor.evaluate_security_posture(None)
    assert with_rows["score"] == without["score"]
