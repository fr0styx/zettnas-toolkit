"""B11 (UX-26): Getting started invites someone, sends phone backup to Backup, and shows only
the steps the person's role can open."""

from backend.services import getting_started as gs
from backend.users_db import create_user, get_user_by_username


def _ids(scopes):
    return [i["id"] for i in gs.checklist("someone", scopes=scopes)["items"]]


def test_an_owner_sees_every_step_with_invite_after_shares():
    ids = _ids(["*"])
    assert ids.index("invite") == ids.index("share" if "share" in ids else "share_host") + 1
    assert {"backup", "alerts", "ai_folder", "app", "phone_backup"} <= set(ids)


def test_a_kid_sees_only_what_a_kid_can_open():
    assert _ids(["shares:read", "shares:user_write"]) == ["password", "two_factor", "phone_backup"]


def test_a_backup_operator_sees_backup_but_not_shares_apps_or_people():
    ids = _ids(["backup:*", "storage:read", "shares:read", "system:view", "logs:read"])
    assert "backup" in ids and not {"share", "share_host", "app", "invite", "alerts"} & set(ids)


def test_phone_backup_opens_the_backup_page():
    row = next(i for i in gs.checklist("someone", scopes=["*"])["items"] if i["id"] == "phone_backup")
    assert row["open"] == "mgmt-pane-backups"


def test_invite_is_done_once_someone_else_has_an_account():
    if not get_user_by_username("gs_family"):
        create_user("gs_family", "Family", "GoodPass123!", role_id="kid")
    row = next(i for i in gs.checklist("admin", scopes=["*"])["items"] if i["id"] == "invite")
    assert row["done"] is True


def test_the_api_uses_the_person_s_rights(client):
    if not get_user_by_username("gs_kid"):
        create_user("gs_kid", "Kid", "GoodPass123!", role_id="kid")
    token = client.post("/api/auth/login", json={"username": "gs_kid", "password": "GoodPass123!"}).json()["token"]
    items = client.get("/api/setup/checklist", headers={"Authorization": f"Bearer {token}"}).json()["items"]
    assert [i["id"] for i in items] == ["password", "two_factor", "phone_backup"]
