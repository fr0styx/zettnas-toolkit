"""NUX-5: the Overview shows each person what they can act on; the rest says who can."""

from backend.auth import has_scope
from backend.services import status_summary as ss

ITEMS = [
    {"kind": "drive_failing", "level": "critical", "open": "drives"},
    {"kind": "default_password", "level": "warning", "open": "settings"},
    {"kind": "timezone_unset", "level": "warning", "open": "time"},
    {"kind": "on_battery", "level": "warning", "open": "power"},
    {"kind": "unknown", "level": "warning", "open": None},
]


def can(scopes):
    return lambda s: has_scope(scopes, s)


def test_an_admin_sees_everything_as_it_is():
    assert ss.for_viewer(ITEMS, can(["*"])) == ITEMS


def test_family_is_told_who_can_fix_it_and_spared_admin_chores():
    out = ss.for_viewer(ITEMS, can(["shares:read", "system:view"]))
    kinds = [i["kind"] for i in out]
    assert "default_password" not in kinds and "timezone_unset" not in kinds
    drive = next(i for i in out if i["kind"] == "drive_failing")
    assert drive["open"] is None and drive["tell_admin"] is True
    assert next(i for i in out if i["kind"] == "unknown") == ITEMS[-1]


def test_a_storage_admin_can_open_drive_items():
    out = ss.for_viewer(ITEMS, can(["storage:*", "system:view"]))
    assert next(i for i in out if i["kind"] == "drive_failing")["open"] == "drives"


def test_summary_and_api_use_the_person(client, auth_headers, monkeypatch):
    monkeypatch.setattr(ss, "CHECKS", (lambda: [dict(ITEMS[1])],))
    assert ss.summary()["items"][0]["kind"] == "default_password"
    assert ss.summary(can(["system:view"])) == {"ok": True, "items": []}
    r = client.get("/api/system/status-summary", headers=auth_headers)
    assert r.status_code == 200 and r.json()["items"][0]["kind"] == "default_password"  # the admin
