"""Getting started checklist (UX-1)."""

from unittest.mock import patch

from backend.services import getting_started as gs


def test_items_follow_the_system_state():
    with (
        patch.object(gs, "_password_changed", return_value=True),
        patch.object(gs, "_has_share", return_value=False),
        patch.object(gs, "_has_app", return_value=True),
        patch.object(gs, "_has_backup", return_value=False),
        patch.object(gs, "_two_factor", return_value=False),
        patch.object(gs, "_ai_has_files", return_value=False),
        patch.object(gs, "_alerts_set_up", side_effect=RuntimeError("no config")),
    ):
        data = gs.checklist("admin", is_admin=True)
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id["password"]["done"] and by_id["app"]["done"]
    assert not by_id["share"]["done"] and by_id["share"]["open"] == "mgmt-pane-storage-shares"
    assert by_id["alerts"]["done"] is False  # a failing check counts as not done
    assert data["total"] == 7 and data["done"] == 2 and not data["complete"]


def test_non_admins_only_see_their_own_items():
    data = gs.checklist("eve", is_admin=False)
    assert [i["id"] for i in data["items"]] == ["password", "two_factor"]


def test_endpoint(client, auth_headers):
    body = client.get("/api/setup/checklist", headers=auth_headers).json()
    assert {"items", "done", "total", "complete"} <= set(body)
    assert body["items"][0]["id"] == "password"
