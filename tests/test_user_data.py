"""One person's data, handed over or forgotten (B8): chats, Zetty's log, what search learned."""

import json
import sqlite3

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend import config, users_db
from backend.auth import AuthenticatedPrincipal
from backend.services import ai_access, user_data
from backend.services import ai_conversations_db as conv


def principal(user, scopes=()):
    return AuthenticatedPrincipal(
        user_id=user["id"], username=user["username"], role_id=user["role_id"], scopes=list(scopes)
    )


def request():
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1), "path_params": {}})


class FakeIndex:
    """The two things user_data asks of the search index."""

    def __init__(self, paths):
        self.forgotten = []
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE indexed_files (canonical_path TEXT, file_name TEXT, indexed_at REAL)")
        self.db.executemany("INSERT INTO indexed_files VALUES (?, ?, 1.0)", [(p, p.rsplit("/", 1)[-1]) for p in paths])

    def _get_conn(self, readonly=False):
        class Conn:
            def __init__(s, db):
                s.db = db

            def execute(s, *a):
                return s.db.execute(*a)

            def close(s):
                pass

        return Conn(self.db)

    def forget_folder(self, path):
        self.forgotten.append(path)
        return {"files": 2}


@pytest.fixture
def family(tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    pool = tmp_path / "pool"
    monkeypatch.setattr(config, "USERS_DB_PATH", db)
    monkeypatch.setattr(users_db, "USERS_DB_PATH", db, raising=False)
    monkeypatch.setattr(config, "POOL_PATH", str(pool))
    monkeypatch.setattr(conv, "get_db_path", lambda: str(tmp_path / "conv.db"))
    conv.init_conversations_db(str(tmp_path / "conv.db"))
    users_db.init_users_db(db)
    mum = users_db.create_user("mum", "Mum", "Mum-Pass-123", role_id="superadmin", db_path=db)
    lea = users_db.create_user("lea", "Lea", "Lea-Pass-123", role_id="kid", db_path=db)
    home = str(pool / "homes" / "lea")
    index = FakeIndex([f"{home}/school/essay.docx", f"{home}/notes.md", str(pool / "family" / "recipes.md")])
    monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", lambda: index)
    uid = lea["id"].lower()
    c = conv.create_conversation(uid, "Homework")
    conv.append_message(c["id"], uid, "user", "what is photosynthesis")
    ai_access.log_request(principal(lea), "chat", "qwen3:4b", False, "answered")
    return {"mum": mum, "lea": lea, "index": index, "home": home}


def test_the_export_holds_everything_but_secrets(family):
    data = user_data.export_user(users_db.get_user_by_id(family["lea"]["id"]))
    text = json.dumps(data, default=str)
    assert data["account"]["username"] == "lea" and "password_hash" not in text and "Lea-Pass" not in text
    assert data["chats"][0]["title"] == "Homework"
    assert any("photosynthesis" in m["content"] for m in data["chats"][0]["messages"])
    assert data["ai_requests"][0]["username"] == "lea"
    assert data["search_index"]["folder"] == family["home"]
    assert [f["name"] for f in data["search_index"]["files"]] == ["notes.md", "essay.docx"]  # only her folder


def test_a_part_that_fails_does_not_spoil_the_export(family, monkeypatch):
    monkeypatch.setattr(user_data, "_chats", lambda u: 1 / 0)
    data = user_data.export_user(family["lea"])
    assert "error" in data["chats"] and data["account"]["username"] == "lea"


def test_erasing_forgets_chats_the_log_and_what_search_learned(family):
    lea = family["lea"]
    done = user_data.erase_user_data(lea)
    assert done["chats"] == 1 and done["ai_log"] >= 1 and done["index"] == {"files": 2}
    assert family["index"].forgotten == [family["home"]]
    data = user_data.export_user(lea)
    assert data["chats"] == [] and data["ai_requests"] == []
    with pytest.raises(ValueError):
        user_data.erase_user_data(lea, ("everything",))


def test_only_the_person_or_an_administrator_may(family):
    from backend.api import user_data as api

    lea, mum = family["lea"], family["mum"]
    me = api.export_user_data(lea["id"], request(), principal(lea))
    assert me.headers["content-disposition"].startswith('attachment; filename="zettnas-data-lea-')
    assert json.loads(me.body)["account"]["username"] == "lea"
    with pytest.raises(HTTPException) as e:
        api.export_user_data(mum["id"], request(), principal(lea))
    assert e.value.status_code == 403
    assert api.export_user_data(lea["id"], request(), principal(mum, ["users:read"])).status_code == 200
    with pytest.raises(HTTPException):
        api.erase_user_data(lea["id"], api.EraseRequest(parts=["chats"]), request(), principal(mum, ["users:read"]))
    out = api.erase_user_data(lea["id"], api.EraseRequest(parts=["chats"]), request(), principal(mum, ["users:delete"]))
    assert out["erased"] == {"chats": 1}
    with pytest.raises(HTTPException) as e:
        api.export_user_data("nobody", request(), principal(mum, ["users:read"]))
    assert e.value.status_code == 404
    events = [r["event"] for r in user_data._security_events(mum)]
    assert "user.data_exported" in events and "user.data_erased" in events


def test_erasing_asks_for_confirmation():
    from backend.api.user_data import router

    route = next(r for r in router.routes if r.path.endswith("/erase-data"))
    assert len(route.dependant.dependencies) >= 2  # the confirmation and the principal


def test_deleting_an_account_forgets_its_data(family, monkeypatch):
    from backend.api import auth as auth_api

    erased = []
    monkeypatch.setattr(user_data, "erase_user_data", lambda u, parts=user_data.PARTS: erased.append(u["username"]))
    res = auth_api.delete_user_endpoint(family["lea"]["id"], request(), principal(family["mum"], ["users:delete"]))
    assert res == {"status": "ok"} and erased == ["lea"]
