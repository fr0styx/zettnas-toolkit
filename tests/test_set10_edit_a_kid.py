"""SET-10: a kid could not be edited. The dialog sent an empty role, the server failed with
"Something went wrong" and saved nothing."""

import pytest

from backend import users_db

PW = "a-long-enough-pass-1"


@pytest.fixture
def kid(client):
    user = users_db.create_user("set10ed", "Edda", PW, role_id="kid")
    yield user
    users_db.delete_user(user["id"])


def test_an_empty_role_is_not_a_role_and_the_rest_is_saved(client, auth_headers, kid):
    r = client.put(
        f"/api/users/{kid['id']}",
        json={"display_name": "Edda K.", "role_id": "", "email": "e@example.org"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    saved = users_db.get_user_by_id(kid["id"])
    assert saved["display_name"] == "Edda K." and saved["role_id"] == "kid"


def test_an_unknown_role_is_refused_in_plain_words(client, auth_headers, kid):
    r = client.put(f"/api/users/{kid['id']}", json={"role_id": "wizard"}, headers=auth_headers)
    assert r.status_code == 400 and "wizard" in str(r.json())
    assert users_db.get_user_by_id(kid["id"])["role_id"] == "kid"


def test_a_kid_can_be_made_a_family_member_and_back(client, auth_headers, kid):
    assert (
        client.put(f"/api/users/{kid['id']}", json={"role_id": "share_user"}, headers=auth_headers).status_code == 200
    )
    assert users_db.get_user_by_id(kid["id"])["role_id"] == "share_user"
    assert client.put(f"/api/users/{kid['id']}", json={"role_id": "kid"}, headers=auth_headers).status_code == 200
    assert users_db.get_user_by_id(kid["id"])["role_id"] == "kid"
