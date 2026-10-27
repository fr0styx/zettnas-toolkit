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
        patch.object(gs, "_host_managed", return_value=""),
        patch.object(gs, "_phone_backs_up", return_value=False),
    ):
        data = gs.checklist("admin", is_admin=True)
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id["password"]["done"] and by_id["app"]["done"]
    assert not by_id["share"]["done"] and by_id["share"]["open"] == "mgmt-pane-storage-shares"
    assert by_id["alerts"]["done"] is False  # a failing check counts as not done
    assert data["total"] == 8 and data["done"] == 2 and not data["complete"]


def test_non_admins_only_see_their_own_items():
    data = gs.checklist("eve", is_admin=False)
    # backing up their own phone is everyone's (B8)
    assert [i["id"] for i in data["items"]] == ["password", "two_factor", "phone_backup"]


def test_endpoint(client, auth_headers):
    body = client.get("/api/setup/checklist", headers=auth_headers).json()
    assert {"items", "done", "total", "complete"} <= set(body)
    assert body["items"][0]["id"] == "password"


def test_on_a_host_that_makes_shares_the_row_says_so():
    """UX-17: Unraid or TrueNAS make shares; the row points there and counts the host's shares."""
    with patch.object(gs, "_host_managed", return_value="unraid"), patch.object(gs, "_has_share", return_value=True):
        data = gs.checklist("admin", is_admin=True)
    row = next(i for i in data["items"] if i["id"].startswith("share"))
    assert row == {"id": "share_host", "open": "mgmt-pane-storage-shares", "done": True, "host": "unraid"}
    with patch.object(gs, "_host_managed", side_effect=RuntimeError("no platform")):
        assert any(i["id"] == "share" for i in gs.checklist("admin", is_admin=True)["items"])


def test_host_shares_count(monkeypatch):
    from types import SimpleNamespace

    from backend.hardware import pal_storage
    from backend.services import nfs_engine, samba_engine

    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: SimpleNamespace(list_shares=lambda: []))
    monkeypatch.setattr(nfs_engine, "get_nfs_engine", lambda: SimpleNamespace(list_exports=lambda: []))
    adapter = SimpleNamespace(
        list_shares=lambda: ["media"],
        get_capabilities=lambda: SimpleNamespace(is_observer_mode=True),
        get_platform_type=lambda: SimpleNamespace(value="truenas"),
    )
    monkeypatch.setattr(pal_storage, "get_storage_platform", lambda: adapter)
    assert gs._has_share() is True and gs._host_managed() == "truenas"
