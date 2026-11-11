"""SET-03: two answers that carried a secret.

- The answer to "create a person" returned the stored record as it is, password record included;
  the read and update routes already cleaned theirs.
- The list of cloud drives returned the second password of an encrypted remote in rclone's
  reversible form, to every account that may read storage.
"""

from backend.services.rclone_engine import is_sensitive_key
from backend.users_db import delete_user, get_user_by_username


def test_creating_a_person_answers_without_their_password_record(client, auth_headers):
    body = {"username": "set03_new", "display_name": "New", "password": "GoodPass123!", "role_id": "share_user"}
    res = client.post("/api/users", json=body, headers=auth_headers)
    try:
        assert res.status_code == 200, res.text
        user = res.json()["user"]
        assert user["username"] == "set03_new" and user["role_id"] == "share_user"
        for secret in ("password_hash", "mfa_secret", "mfa_recovery_codes_json", "token_hash"):
            assert secret not in user, secret
        assert "argon2" not in res.text
    finally:
        made = get_user_by_username("set03_new")
        if made:
            delete_user(made["id"])


def test_every_password_of_a_cloud_drive_counts_as_a_secret():
    for key in ("pass", "password", "password2", "pass2", "Password2", "token", "client_secret", "sftp_pass"):
        assert is_sensitive_key(key), key
    for key in ("type", "host", "user", "remote", "filename_encryption", "passive", "compass"):
        assert not is_sensitive_key(key), key
