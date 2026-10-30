"""NSEC-13 (file activity: the Auditor sees whose home, not what; export and erase), NSEC-16
(compose and update checks need container scopes), NSEC-17 (plain http across the internet)."""

import time

import pytest

from backend.services import file_activity, offsite_backup, user_data

HOMES = "/mnt/user/homes"


def test_mask_home():
    assert file_activity.mask_home(f"{HOMES}/alice/tax/2026.pdf", HOMES) == f"{HOMES}/alice/…"
    assert file_activity.mask_home(f"{HOMES}/alice", HOMES) == f"{HOMES}/alice"
    assert file_activity.mask_home("/mnt/user/photos/a.jpg", HOMES) == "/mnt/user/photos/a.jpg"
    assert file_activity.mask_home("", HOMES) == ""


@pytest.fixture
def rows(monkeypatch):
    from backend.db import db_session, init_db

    init_db()
    with db_session() as conn:
        conn.execute("DELETE FROM file_activity")
    from backend import auth

    token = auth.CLIENT_IP_CTX.set("192.0.2.7")
    try:
        p = type("P", (), {"username": "alice", "is_api_token": False})()
        file_activity.record("delete", f"{HOMES}/alice/diary.txt", p)
        file_activity.record("rename", "/mnt/user/photos/a.jpg", p, target=f"{HOMES}/alice/a.jpg")
        file_activity.record("upload", "/mnt/user/photos/b.jpg", type("P", (), {"username": "bob"})())
    finally:
        auth.CLIENT_IP_CTX.reset(token)


def test_search_hides_home_names_and_does_not_look_inside(rows):
    hidden = file_activity.search(hide_under=HOMES)
    assert {r["path"] for r in hidden} >= {f"{HOMES}/alice/…", "/mnt/user/photos/a.jpg"}
    assert all("diary" not in r["path"] and "diary" not in r["target"] for r in hidden)
    assert file_activity.search(q="diary", hide_under=HOMES) == []
    assert len(file_activity.search(q="diary")) == 1  # an administrator still finds it


def test_export_and_erase(rows):
    mine = file_activity.for_user("ALICE")
    assert len(mine) == 2 and mine[0]["ip"] == "192.0.2.7" and "username" not in mine[0]
    changed = file_activity.forget_user("alice", "erased-x", f"{HOMES}/alice")
    assert changed == 2
    left = file_activity.search()
    assert {r["username"] for r in left} == {"erased-x", "bob"}
    assert all(r["ip"] == "" for r in left if r["username"] == "erased-x")
    assert all("diary" not in r["path"] and "a.jpg" not in r["target"] for r in left if r["username"] == "erased-x")
    assert file_activity.forget_user("", "x") == 0


def test_user_data_knows_the_store(monkeypatch):
    assert "file_activity" in user_data.PARTS and "file_activity" in user_data.STORES
    seen = {}
    monkeypatch.setattr(file_activity, "forget_user", lambda u, a, h="": seen.update(u=u, a=a, h=h) or 3)
    monkeypatch.setattr(user_data, "_home", lambda u: f"{HOMES}/alice")
    done = user_data.erase_user_data({"id": "u1", "username": "alice"}, ("file_activity",))
    assert done == {"file_activity": 3} and seen["a"].startswith("erased-") and seen["h"] == f"{HOMES}/alice"


def test_api_masks_for_the_auditor(client, auth_headers, monkeypatch):
    calls = []
    monkeypatch.setattr(file_activity, "search", lambda **k: calls.append(k) or [])
    assert client.get("/api/fs/activity", headers=auth_headers).status_code == 200
    assert calls[-1]["hide_under"] == ""  # the admin holds users:read
    from backend.auth import AuthenticatedPrincipal, get_current_principal
    from backend.main import app

    auditor = AuthenticatedPrincipal(username="aud", scopes=["audit:read", "system:view"], role="Auditor")
    app.dependency_overrides[get_current_principal] = lambda: auditor
    try:
        from backend.api.files import activity

        activity.fs_activity(q="", user="", action="", days=90, limit=10, before=None, principal=auditor)
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
    assert calls[-1]["hide_under"].endswith("/homes")


def test_container_scopes():
    import inspect

    from backend.api import docker

    src = inspect.getsource(docker)
    compose = src[src.index('"/docker/containers/{container_id}/compose"') :][:200]
    assert "system:view" not in compose
    check = src[src.index('"/docker/updates/check"') :][:120]
    assert 'require_scope("containers:manage")' in check


@pytest.mark.parametrize(
    "location,outside",
    [
        ("rest:http://friend.example.com:8000/me/", True),
        ("rest:http://1.1.1.1:8000/me/", True),
        ("rest:http://192.168.1.20:8000/me/", False),
        ("rest:http://100.101.102.103:8000/me/", False),
        ("rest:http://nas:8000/me/", False),
        ("rest:http://nas.local:8000/me/", False),
        ("rest:http://friend.tail1234.ts.net:8000/me/", False),
        ("rest:http://[fd00::5]:8000/me/", False),
        ("rest:http://[2606:4700:4700::1111]:8000/me/", True),
        ("rest:https://friend.example.com/me/", False),
        ("rclone:cloud:x", False),
    ],
)
def test_plain_http_outside(location, outside):
    assert offsite_backup.plain_http_outside(location) is outside


def test_public_repo_carries_it():
    repo = {"location": "rest:http://friend.example.com:8000/me/", "paths": [], "created_at": time.time()}
    assert offsite_backup._public(repo)["plain_http"] is True


def test_template_note_warns():
    from backend.services.catalog_templates import CURATED_APP_CATALOG

    notes = [a["credentials"]["note"] for a in CURATED_APP_CATALOG if "restic" in (a.get("tags") or [])]
    assert notes and all("Tailscale" in n for n in notes)
