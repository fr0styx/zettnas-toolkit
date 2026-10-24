"""Usernames name each person\x27s private folder (<pool>/homes/<username>), so a name that
leaves that folder (".." would be the whole pool) is refused however the account is made."""

import pytest

from backend.services.oidc import _clean_username
from backend.users_db import create_user, unsafe_username


@pytest.mark.parametrize("name", ["..", "...", ".hidden", "a/b", "a\\\\b", "x\\x00y", "tab\\tname"])
def test_unsafe_usernames(name):
    assert unsafe_username(name)


@pytest.mark.parametrize("name", ["alice", "john.doe", "j-s_2", "_svc"])
def test_ordinary_usernames(name):
    assert not unsafe_username(name)


def test_accounts_cannot_be_named_after_a_parent_folder():
    with pytest.raises(ValueError):
        create_user(username="..", display_name="x", password="Long-Enough-Pass-1")
    with pytest.raises(ValueError):
        create_user(username=".config", display_name="x", password="Long-Enough-Pass-1")


def test_sign_in_providers_cannot_choose_a_parent_folder():
    assert _clean_username("..") not in ("..", ".")
    assert not _clean_username("..").startswith(".")
    assert _clean_username(".alice@example.com") == "alice"
    assert _clean_username("john.doe@example.com") == "john.doe"


def test_the_admin_form_refuses_a_leading_dot(client, auth_headers):
    r = client.post("/api/users", json={"username": "..", "password": "Long-Enough-Pass-1"}, headers=auth_headers)
    assert r.status_code == 422
