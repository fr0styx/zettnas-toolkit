"""Destructive-action standard: 428 until a single-use, bound confirm token is sent."""

import pytest

from backend import confirmations

pytestmark = pytest.mark.real_confirmations


def _token(client, headers, action, target=""):
    res = client.post("/api/confirmations", json={"action": action, "target": target}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["token"]


def test_trash_empty_needs_a_token_and_it_is_single_use(client, auth_headers):
    res = client.delete("/api/fs/trash/empty", headers=auth_headers)
    assert res.status_code == 428
    body = res.json()
    assert body["error"] == "confirmation_required" and body["action"] == "fs.trash.empty" and body["summary"]

    tok = _token(client, auth_headers, "fs.trash.empty")
    ok = client.delete("/api/fs/trash/empty", headers={**auth_headers, "X-Confirm-Token": tok})
    assert ok.status_code != 428
    again = client.delete("/api/fs/trash/empty", headers={**auth_headers, "X-Confirm-Token": tok})
    assert again.status_code == 428


def test_token_is_bound_to_action_and_target(client, auth_headers):
    tok = _token(client, auth_headers, "users.delete", "someone-else")
    res = client.delete("/api/users/target-user", headers={**auth_headers, "X-Confirm-Token": tok})
    assert res.status_code == 428
    tok = _token(client, auth_headers, "fs.trash.empty")
    res = client.post("/api/system/reboot", headers={**auth_headers, "X-Confirm-Token": tok})
    assert res.status_code == 428


def test_unknown_action_and_expiry(client, auth_headers, monkeypatch):
    res = client.post("/api/confirmations", json={"action": "anything"}, headers=auth_headers)
    assert res.status_code == 400
    tok = _token(client, auth_headers, "system.reboot")
    confirmations._pending[tok]["expires_at"] = 0  # expired
    res = client.post("/api/system/reboot", headers={**auth_headers, "X-Confirm-Token": tok})
    assert res.status_code == 428


def test_every_guarded_route_answers_428_without_a_token(client, auth_headers):
    routes = [
        ("delete", "/api/fs/trash/empty"),
        ("delete", "/api/storage/pools/p1"),
        ("delete", "/api/docker/containers/c1"),
        ("delete", "/api/users/u1"),
        ("post", "/api/system/reboot"),
        ("post", "/api/system/shutdown"),
        ("post", "/api/system/updates/apply"),
    ]
    for method, path in routes:
        kwargs = {"json": {}} if method == "post" else {}
        res = getattr(client, method)(path, headers=auth_headers, **kwargs)
        assert res.status_code in (428, 404, 422), (path, res.status_code)
        if res.status_code == 404:
            pytest.fail(f"{path} not found; route path changed?")
