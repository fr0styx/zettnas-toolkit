"""Who may ask Zetty (B8): a switch per role, kids and guests off until turned on, and a request log
that keeps who asked when, never what."""

import time

import pytest

from backend import config, users_db
from backend.auth import AuthenticatedPrincipal
from backend.errors import ShownServerError
from backend.services import ai_access


def who(role, name="someone"):
    return AuthenticatedPrincipal(user_id=name, username=name, role_id=role, scopes=["shares:read"])


@pytest.fixture
def cfg(monkeypatch):
    state = {"ai_role_access": {"kid": False, "guest": False}}

    class Engine:
        def get_config(self):
            return dict(state)

    monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", lambda: Engine())
    return state


def test_kids_and_guests_start_off_everyone_else_on(cfg):
    assert not ai_access.allowed(who("kid")) and not ai_access.allowed(who("guest"))
    assert ai_access.allowed(who("share_user")) and ai_access.allowed(who("superadmin"))
    assert ai_access.allowed(who("a_custom_role"))  # a role nobody switched is on
    cfg.pop("ai_role_access")  # an install that never saved the setting
    assert not ai_access.allowed(who("kid"))


def test_an_administrator_turns_them_on_but_cannot_lock_out_the_superadmin(cfg):
    cfg["ai_role_access"] = {"kid": True, "share_user": False, "superadmin": False}
    assert ai_access.allowed(who("kid")) and not ai_access.allowed(who("share_user"))
    assert ai_access.allowed(who("superadmin"))
    assert ai_access.clean_switches({"kid": True, "superadmin": False}) == {"kid": True}
    for bad in ({"kid": "yes"}, ["kid"], {"": True}, {"x" * 65: True}):
        with pytest.raises(ValueError):
            ai_access.clean_switches(bad)


def test_the_chat_refuses_a_role_that_is_off_and_logs_it(cfg):
    with pytest.raises(ShownServerError) as e:
        ai_access.require_ai_access(who("kid", "lea"))
    assert e.value.status_code == 403 and e.value.error == "ai_off_for_role"
    assert ai_access.require_ai_access(who("share_user", "dad")).username == "dad"
    rows = ai_access.recent(5, "lea")
    assert rows[0]["outcome"] == "refused" and rows[0]["role"] == "kid"


def test_the_log_keeps_who_and_when_never_the_text(cfg):
    ai_access.log_request(who("share_user", "dad2"), "chat", "qwen3:4b", True, "answered", 1234, now=time.time() - 5)
    ai_access.log_request(who("share_user", "dad2"), "chat", "", False, "something odd")
    rows = ai_access.recent(10, "dad2")
    assert rows[0]["outcome"] == "failed"  # an unknown outcome is recorded as a failure
    assert {k: rows[1][k] for k in ("username", "role", "model", "web", "outcome", "ms")} == {
        "username": "dad2",
        "role": "share_user",
        "model": "qwen3:4b",
        "web": True,
        "outcome": "answered",
        "ms": 1234,
    }
    assert set(rows[1]) == {"ts", "username", "role", "kind", "model", "web", "outcome", "ms"}
    assert ai_access.recent(1)  # everyone's, newest first


def test_old_rows_are_pruned(cfg):
    ai_access._PRUNED["at"] = 0
    old = time.time() - (ai_access.LOG_DAYS + 1) * 86400
    ai_access.log_request(who("guest", "old"), "chat", "", False, "refused", now=old)
    ai_access._PRUNED["at"] = 0
    ai_access.log_request(who("guest", "new"), "chat", "", False, "refused")
    assert ai_access.recent(10, "old") == [] and ai_access.recent(10, "new")


def test_every_role_is_listed_with_its_switch(cfg, tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    monkeypatch.setattr(users_db, "USERS_DB_PATH", db, raising=False)
    users_db.init_users_db(db)
    roles = {r["id"]: r for r in ai_access.roles_with_access()}
    assert roles["kid"]["on"] is False and roles["guest"]["on"] is False
    assert roles["share_user"]["on"] is True
    assert roles["superadmin"]["on"] and roles["superadmin"]["locked"]


def test_every_chat_route_checks_the_switch():
    from backend.api.media import router

    chat = [r for r in router.routes if getattr(r, "path", "").endswith(("/chat", "/chat/stream"))]
    assert len(chat) == 4
    for r in chat:
        assert any(d.call is ai_access.require_ai_access for d in r.dependant.dependencies), r.path


def test_the_setting_is_saved_through_the_ai_config(tmp_path, monkeypatch):
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine, "RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    eng = rag_engine.RagSearchEngine(db_path=str(tmp_path / "x.db"))
    try:
        assert eng.get_config()["ai_role_access"] == {"kid": False, "guest": False}
        eng.update_config({"ai_role_access": {"kid": True}})
        assert eng.get_config()["ai_role_access"] == {"kid": True, "guest": False}
    finally:
        eng.close()


def test_the_api_lists_saves_and_answers_for_me(cfg, tmp_path, monkeypatch):
    from backend.api import media

    saved = {}

    class Engine:
        def get_config(self):
            return {"ai_role_access": {"kid": False, "guest": False, **saved}}

        def update_config(self, updates):
            saved.update(updates["ai_role_access"])

    monkeypatch.setattr(media, "get_rag_engine", lambda: Engine())
    monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", lambda: Engine())
    monkeypatch.setattr(ai_access, "roles_with_access", lambda: [{"id": "kid", "on": ai_access.role_access()["kid"]}])
    assert media.get_ai_access()["roles"] == [{"id": "kid", "on": False}]
    assert media.put_ai_access(media.AiAccessUpdate(roles={"kid": True}))["roles"] == [{"id": "kid", "on": True}]
    assert media.get_my_ai_access(who("kid")) == {"allowed": True, "search": False}
    with pytest.raises(media.HTTPException):
        media.put_ai_access(media.AiAccessUpdate(roles={"kid": True, "": False}))
    ai_access.log_request(who("kid", "lea3"), "chat", "", False, "answered")
    assert media.get_ai_requests(limit=5, user="lea3")["requests"][0]["username"] == "lea3"
