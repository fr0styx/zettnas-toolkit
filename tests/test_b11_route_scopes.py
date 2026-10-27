"""B11 (SEC-30): reads and links that reach other people's data need the matching right."""

import pytest

from backend.services import notifications, share_access
from backend.users_db import create_user


def _login(client, username, role_id, password="GoodPass123!"):
    create_user(username, username, password, role_id=role_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()


# --- someone else's data ----------------------------------------------------------------------


def test_an_admin_download_of_someone_elses_data_tells_them(client, auth_headers, monkeypatch):
    told = []
    monkeypatch.setattr(
        notifications, "notify_person", lambda u, title, msg, level="warning": told.append((u, msg)) or True
    )
    kid = create_user("kid_export", "Kid", "GoodPass123!", role_id="kid")
    res = client.get(f"/api/users/{kid['id']}/export", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert told and told[0][0] == "kid_export" and "downloaded" in told[0][1]


def test_downloading_your_own_data_needs_no_confirmation_or_notice(client, monkeypatch):
    told = []
    monkeypatch.setattr(notifications, "notify_person", lambda *a, **k: told.append(a) or True)
    headers = _login(client, "self_export", "share_user")
    me = _me(client, headers)
    res = client.get(f"/api/users/{me.get('id') or me.get('user_id')}/export", headers=headers)
    assert res.status_code == 200, res.text
    assert told == []


@pytest.mark.real_confirmations
def test_downloading_someone_elses_data_is_confirmed_first(client, auth_headers):
    kid = create_user("kid_confirm", "Kid", "GoodPass123!", role_id="kid")
    res = client.get(f"/api/users/{kid['id']}/export", headers=auth_headers)
    assert res.status_code == 428
    assert res.json()["action"] == "users.export_data" and res.json()["target"] == kid["id"]


def test_notify_person_uses_their_own_channel(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"smtp_host": "mail.example"})
    monkeypatch.setattr(notifications, "get_routes", lambda: {"ann": {"ntfy_topic": "ann-topic"}})
    monkeypatch.setattr(
        notifications, "_dispatch_ntfy", lambda cfg, *a: sent.append(("ntfy", cfg["ntfy_topic"])) or True
    )
    monkeypatch.setattr(
        notifications, "_dispatch_apprise", lambda cfg, *a: sent.append(("mail", cfg["email_to"])) or True
    )
    create_user("ann", "Ann", "GoodPass123!", role_id="share_user", email="ann@example.com")
    assert notifications.notify_person("ann", "t", "m") is True
    assert sent == [("ntfy", "ann-topic"), ("mail", "ann@example.com")]
    sent.clear()
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {})
    monkeypatch.setattr(notifications, "get_routes", lambda: {})
    assert notifications.notify_person("ann", "t", "m") is False and sent == []
    assert notifications.notify_person("", "t", "m") is False


# --- container logs -----------------------------------------------------------------------------


def test_container_logs_need_the_containers_right(client, monkeypatch):
    from backend.services import compose_synthesizer

    monkeypatch.setattr(compose_synthesizer, "get_container_logs_chunk", lambda cid, tail: {"lines": ["ok"]})
    auditor = _login(client, "logs_auditor", "auditor")
    family = _login(client, "logs_family", "share_user")
    operator = _login(client, "logs_operator", "app_operator")
    for headers in (auditor, family):
        assert client.get("/api/docker/containers/web/logs", headers=headers).status_code == 403
    assert client.get("/api/docker/containers/web/logs", headers=operator).status_code == 200


# --- share links --------------------------------------------------------------------------------


@pytest.fixture
def media(tmp_path, monkeypatch):
    from backend import config

    root = tmp_path / "user"
    (root / "media").mkdir(parents=True)
    (root / "media" / "a.txt").write_text("x")
    monkeypatch.setattr(config, "POOL_PATH", str(root))
    monkeypatch.setattr("backend.config.ALLOWED_BROWSE_ROOTS", [str(root)])
    monkeypatch.setattr(
        share_access, "known_shares", lambda: [{"name": "media", "path": str(root / "media"), "samba": None}]
    )
    share_access.invalidate()
    return root / "media" / "a.txt"


def test_a_backup_operator_cannot_publish_files(client, media):
    headers = _login(client, "links_backup", "backup_operator")
    res = client.post("/api/share-links", json={"path": str(media)}, headers=headers)
    assert res.status_code == 403


def test_a_public_link_needs_write_on_that_folder(client, media):
    headers = _login(client, "links_reader", "share_user")
    share_access.save_config({"shares": {"media": {"users": {"links_reader": "read"}}}})
    res = client.post("/api/share-links", json={"path": str(media)}, headers=headers)
    assert res.status_code == 403
    share_access.save_config({"shares": {"media": {"users": {"links_reader": "write"}}}})
    res = client.post("/api/share-links", json={"path": str(media)}, headers=headers)
    assert res.status_code == 200, res.text
