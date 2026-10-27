"""B11 (SEC-32): the security log keeps which tool ran, not what was asked; it forgets after a
year (configurable); erasing someone replaces their name with a pseudonym; the export holds
every store with something of theirs."""

import json
import os
import time

from backend import config, users_db
from backend.services import user_data
from backend.users_db import create_user, get_user_by_username, log_security_event, users_db_session


def _person(name):
    return get_user_by_username(name) or create_user(name, name, "GoodPass123!", role_id="share_user")


def _events(where="1=1", args=()):
    with users_db_session() as conn:
        return conn.execute(
            f"SELECT event_type, actor_id, actor_username, actor_ip, details_json, timestamp FROM security_audit_log WHERE {where}",
            args,
        ).fetchall()


def test_a_tool_call_is_logged_by_name_without_what_was_asked():
    from backend.auth import AuthenticatedPrincipal
    from backend.services.chat_tool_registry import _audit_tool_call

    who = AuthenticatedPrincipal(user_id="u_tool", username="tool_lea", role_id="share_user", scopes=["shares:read"])
    _audit_tool_call(
        "search_nas_knowledge", {"query": "my salary 4812 and IBAN CH93"}, who, False, "chat", {"status": "ok"}
    )
    row = _events("actor_id = ?", ("u_tool",))[-1]
    details = json.loads(row[4])
    assert details["tool"] == "search_nas_knowledge" and details["arg_names"] == ["query"]
    assert "4812" not in row[4] and "IBAN" not in row[4] and "args" not in details


def test_events_older_than_the_retention_are_forgotten(monkeypatch):
    old = time.time() - 400 * 86400
    with users_db_session() as conn:
        conn.execute(
            "INSERT INTO security_audit_log (event_type, status, details_json, timestamp) VALUES ('old.event', 'success', '{}', ?)",
            (old,),
        )
    monkeypatch.setattr(config, "AUDIT_RETENTION_DAYS", 0)  # 0 keeps everything
    users_db._AUDIT_PRUNED["at"] = 0.0
    log_security_event("new.event", "success")
    assert _events("event_type = 'old.event'")
    monkeypatch.setattr(config, "AUDIT_RETENTION_DAYS", 365)
    users_db._AUDIT_PRUNED["at"] = 0.0
    log_security_event("new.event", "success")
    assert not _events("event_type = 'old.event'") and _events("event_type = 'new.event'")


def test_erasing_someone_keeps_the_events_but_not_who(monkeypatch):
    lea = _person("erase_lea")
    log_security_event("auth.login", "success", actor_id=lea["id"], actor_username="erase_lea", actor_ip="192.0.2.7")
    done = user_data.erase_user_data(lea, ("security_log",))
    assert done["security_log"] >= 1
    assert not _events("actor_id = ? OR actor_username = ?", (lea["id"], "erase_lea"))
    alias = _events("actor_username LIKE 'erased-%'")
    assert alias and all(r[3] == "" for r in alias)
    assert "security_log" in user_data.PARTS  # deleting an account erases every part


def test_the_export_holds_every_store(monkeypatch):
    ann = _person("export_ann")
    from backend.api import calendar
    from backend.api.files import share_links
    from backend.services import notifications

    calendar._save_calendar_store(
        {
            "notes": [
                {"id": "n1", "title": "Dentist", "owner": ann["id"]},
                {"id": "n2", "title": "Not hers", "owner": "x"},
            ],
            "feeds": [],
            "feed_events": [],
        }
    )
    share_links._save_share_links(
        {"tok1": {"token": "tok1", "path": "/mnt/user/a", "created_by": "export_ann", "password_hash": "h"}}
    )
    with open(os.path.join(config.DATA_DIR, "fm_favorites.json"), "w") as f:
        json.dump({"export_ann": [{"path": "/mnt/user/a", "name": "a"}]}, f)
    monkeypatch.setattr(notifications, "get_routes", lambda: {"export_ann": {"ntfy_topic": "ann"}})

    data = user_data.export_user(ann)
    assert set(data) == {"format", "exported_at", *user_data.STORES}
    assert [n["title"] for n in data["calendar"]["notes"]] == ["Dentist"]
    assert data["share_links"] == [{"path": "/mnt/user/a", "created_by": "export_ann"}]
    assert data["favorites"][0]["path"] == "/mnt/user/a"
    assert data["alert_route"] == {"ntfy_topic": "ann"}
    assert data["immich"]["connected"] is False
    assert "tok1" not in json.dumps(data, default=str)
