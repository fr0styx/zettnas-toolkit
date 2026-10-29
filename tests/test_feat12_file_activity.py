"""FEAT-12: who deleted, moved, renamed, restored or uploaded what; searchable, 90 days kept."""

import sqlite3
import time

import pytest

from backend import db
from backend.auth import AuthenticatedPrincipal
from backend.services import file_activity


@pytest.fixture(autouse=True)
def _fresh_log():
    db.init_db()
    with db.db_session() as conn:
        conn.execute("DELETE FROM file_activity")
    file_activity._last_prune[0] = 0.0
    yield


KIM = AuthenticatedPrincipal({"username": "kim", "role_id": "share_user", "scopes": []})


def test_an_entry_is_written_and_found():
    assert file_activity.record("rename", "/mnt/user/Docs/a.pdf", KIM, target="/mnt/user/Docs/b.pdf")
    items = file_activity.search()
    assert len(items) == 1
    it = items[0]
    assert (it["username"], it["action"], it["path"], it["target"]) == (
        "kim",
        "rename",
        "/mnt/user/Docs/a.pdf",
        "/mnt/user/Docs/b.pdf",
    )


def test_search_by_path_person_and_action():
    file_activity.record("delete", "/mnt/user/Docs/tax_2025.pdf", KIM)
    file_activity.record("upload", "/mnt/user/Photos/beach.jpg", AuthenticatedPrincipal({"username": "sam"}))
    file_activity.record("move", "/mnt/user/Docs/old", KIM, target="/mnt/user/Archive")
    assert [i["path"] for i in file_activity.search(q="Archive")] == ["/mnt/user/Docs/old"]  # the new path counts
    assert {i["username"] for i in file_activity.search(user="SAM")} == {"sam"}
    assert [i["action"] for i in file_activity.search(action="delete")] == ["delete"]
    # % and _ are literal, not wildcards
    assert [i["path"] for i in file_activity.search(q="tax_2025")] == ["/mnt/user/Docs/tax_2025.pdf"]
    assert file_activity.search(q="%") == []


def test_newest_first_and_paging():
    for n in range(5):
        file_activity.record("mkdir", f"/mnt/user/f{n}", KIM)
    first = file_activity.search(limit=2)
    assert [i["path"] for i in first] == ["/mnt/user/f4", "/mnt/user/f3"]
    second = file_activity.search(limit=2, before_id=first[-1]["id"])
    assert [i["path"] for i in second] == ["/mnt/user/f2", "/mnt/user/f1"]


def test_entries_older_than_90_days_are_removed(monkeypatch):
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO file_activity (ts, username, action, path) VALUES (?, 'kim', 'delete', '/old')",
            (time.time() - 91 * 86400,),
        )
    file_activity.record("delete", "/new", KIM)
    with db.db_read_session() as conn:
        assert [r[0] for r in conn.execute("SELECT path FROM file_activity")] == ["/new"]


def test_an_unknown_action_is_a_bug():
    with pytest.raises(ValueError):
        file_activity.record("explode", "/x", KIM)
    with pytest.raises(ValueError):
        file_activity.search(action="explode")


def test_a_database_error_never_fails_the_file_operation(monkeypatch):
    monkeypatch.setattr(db, "db_session", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    assert file_activity.record("delete", "/x", KIM) is False


def test_api_token_use_is_marked():
    file_activity.record("upload", "/mnt/user/x", AuthenticatedPrincipal({"username": "kim", "is_api_token": True}))
    assert file_activity.search()[0]["via"] == "api token"


# --- through the file API ---


def test_file_operations_land_in_the_log(client, auth_headers, tmp_path, monkeypatch):
    from backend import config

    pool = tmp_path / "pool"
    (pool / "Docs").mkdir(parents=True)
    (pool / "Docs" / "a.txt").write_text("hi")
    monkeypatch.setattr(config, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    r = client.post(
        "/api/fs/rename", json={"path": str(pool / "Docs" / "a.txt"), "new_name": "b.txt"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    r = client.post("/api/mkdir", json={"path": str(pool / "Docs" / "New")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    r = client.post("/api/fs/delete", json={"path": str(pool / "Docs" / "b.txt")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    log = client.get("/api/fs/activity", headers=auth_headers).json()
    assert [i["action"] for i in log["items"]] == ["delete", "mkdir", "rename"]
    assert log["items"][2]["target"].endswith("/Docs/b.txt") and log["items"][2]["username"] == "admin"
    assert "delete_permanent" in log["actions"] and log["retention_days"] == 90


def test_the_log_is_for_audit_readers_only(client, auth_headers):
    from backend.api.files import activity

    assert client.get("/api/fs/activity?action=explode", headers=auth_headers).status_code == 400
    client.cookies.clear()  # the login above left its session cookie
    assert client.get("/api/fs/activity").status_code == 401
    deps = [d.call for r in activity.router.routes for d in r.dependant.dependencies]
    assert any(getattr(d, "required_scopes", None) == ("audit:read",) for d in deps)
