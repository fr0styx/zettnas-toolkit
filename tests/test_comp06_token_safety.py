"""COMP-06: an API token can be limited to folders, its use is recorded, and the AI client that
used it last is shown, so a family sees what is connected and can revoke it."""

import os
import sqlite3

import pytest
from fastapi import HTTPException

from backend import users_db
from backend.api import mcp
from backend.auth import AuthenticatedPrincipal
from backend.services import path_access
from backend.services.path_access import check_user_path_access, indexed_path_checker, within_token_folders
from backend.services.rag_engine_search import RagSearchMixin

ADMIN = {"user_id": "u1", "username": "admin", "role_id": "superadmin", "scopes": ["*"], "is_api_token": True}


def _token_principal(folders, **extra):
    return AuthenticatedPrincipal({**ADMIN, "folders": folders, "token_id": "t1", **extra})


# --- the allow-list itself ---


def test_folders_are_normalised_and_nested_ones_dropped():
    assert users_db.normalize_token_folders(["/mnt/user/Docs/", "/mnt/user/Docs/Tax", " /mnt/user/Photos "]) == [
        "/mnt/user/Docs",
        "/mnt/user/Photos",
    ]
    assert users_db.normalize_token_folders(None) == []
    assert users_db.normalize_token_folders(["", "  "]) == []


@pytest.mark.parametrize("bad", ["relative/path", "/mnt/user/../etc", "/"])
def test_bad_folders_are_refused(bad):
    with pytest.raises(ValueError):
        users_db.normalize_token_folders([bad])


def test_at_most_twenty_folders():
    with pytest.raises(ValueError):
        users_db.normalize_token_folders([f"/mnt/user/f{i}" for i in range(21)])


def test_within_token_folders_respects_name_boundaries():
    f = ["/mnt/user/Docs"]
    assert within_token_folders("/mnt/user/Docs", f)
    assert within_token_folders("/mnt/user/Docs/a/b.pdf", f)
    assert not within_token_folders("/mnt/user/Docs2/b.pdf", f)
    assert not within_token_folders("/mnt/user", f)
    assert within_token_folders("/mnt/user", f, allow_list=True)  # browsing down to it
    assert within_token_folders("/anything", [])


# --- enforcement ---


def test_a_limited_admin_token_reaches_nothing_outside_its_folders(tmp_path):
    inside = tmp_path / "Docs"
    inside.mkdir()
    (tmp_path / "Other").mkdir()
    p = _token_principal([str(inside)])
    check_user_path_access(str(inside / "a.pdf"), p)
    with pytest.raises(HTTPException) as e:
        check_user_path_access(str(tmp_path / "Other" / "b.pdf"), p)
    assert e.value.status_code == 403
    check_user_path_access(str(tmp_path), p, allow_list=True)
    with pytest.raises(HTTPException):
        check_user_path_access(str(tmp_path), p)


def test_a_symlink_out_of_the_folder_is_refused(tmp_path):
    inside = tmp_path / "Docs"
    inside.mkdir()
    secret = tmp_path / "Secret"
    secret.mkdir()
    os.symlink(secret, inside / "link")
    with pytest.raises(HTTPException):
        check_user_path_access(str(inside / "link" / "x.txt"), _token_principal([str(inside)]))


def test_an_unlimited_token_is_unchanged(tmp_path):
    check_user_path_access(str(tmp_path / "x"), _token_principal([]))


def test_the_index_checker_applies_the_folders_too():
    readable = indexed_path_checker(_token_principal(["/mnt/user/Docs"]))
    assert readable("/mnt/user/Docs/a.pdf")
    assert not readable("/mnt/user/Photos/b.jpg")
    assert indexed_path_checker(_token_principal([]))("/mnt/user/Photos/b.jpg")


def test_search_is_limited_to_the_folders_in_sql():
    sql, params = RagSearchMixin._build_rbac_clause(_token_principal(["/mnt/user/Docs", "/mnt/user/Tax"]))
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE indexed_files (canonical_path TEXT, visibility_tier TEXT, share_name TEXT,"
        " owner_username TEXT, allowed_users_csv TEXT)"
    )
    for path in ("/mnt/user/Docs/a.pdf", "/mnt/user/Docs2/b.pdf", "/mnt/user/Tax/2025.pdf", "/mnt/user/Photos/c.jpg"):
        conn.execute("INSERT INTO indexed_files VALUES (?, 'public_share', '', '', '')", (path,))
    rows = sorted(r[0] for r in conn.execute(f"SELECT canonical_path FROM indexed_files f WHERE {sql}", params))
    assert rows == ["/mnt/user/Docs/a.pdf", "/mnt/user/Tax/2025.pdf"]
    assert RagSearchMixin._build_rbac_clause(_token_principal([])) == ("1=1", [])


# --- tokens through the API ---


def test_a_token_made_for_folders_is_limited_by_them(client, auth_headers, tmp_path):
    r = client.post("/api/tokens", json={"name": "paperless", "folders": ["/mnt/user/Docs/"]}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["folders"] == ["/mnt/user/Docs"]
    raw = r.json()["token"]
    listed = next(t for t in client.get("/api/tokens", headers=auth_headers).json() if t["name"] == "paperless")
    assert listed["folders"] == ["/mnt/user/Docs"] and listed["last_used_at"] is None
    sess = users_db.validate_scoped_api_token(raw)
    assert sess["folders"] == ["/mnt/user/Docs"]


def test_a_bad_folder_is_a_400(client, auth_headers):
    r = client.post("/api/tokens", json={"name": "x", "folders": ["docs"]}, headers=auth_headers)
    assert r.status_code == 400


def test_a_folder_you_cannot_open_cannot_be_given_to_a_token(monkeypatch):
    from backend.api import system

    monkeypatch.setattr(path_access, "indexed_path_checker", lambda principal: lambda path: False)
    with pytest.raises(HTTPException) as e:
        system._token_folders_for(["/mnt/user/Private"], AuthenticatedPrincipal({"username": "kim", "scopes": []}))
    assert e.value.status_code == 403


def test_using_a_token_records_when_and_where(client, auth_headers):
    raw = client.post("/api/tokens", json={"name": "ha", "scopes": ["system:read"]}, headers=auth_headers).json()[
        "token"
    ]
    users_db._TOKEN_USE.clear()
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {raw}"}).status_code == 200
    listed = next(t for t in client.get("/api/tokens", headers=auth_headers).json() if t["name"] == "ha")
    assert listed["last_used_at"] and listed["last_used_ip"]


def test_recording_use_is_throttled_but_a_new_client_always_counts(tmp_path):
    db = str(tmp_path / "users.db")
    users_db.init_users_db(db)
    user = users_db.create_user("kim", "Kim", "a-Long-unique-pw-91", role_id="share_user", db_path=db)
    _raw, meta = users_db.create_scoped_api_token(user["id"], "t", ["system:read"], db_path=db)
    users_db._TOKEN_USE.clear()
    assert users_db.note_token_use(meta["token_id"], "10.0.0.5", db_path=db)
    assert not users_db.note_token_use(meta["token_id"], "10.0.0.5", db_path=db)
    assert users_db.note_token_use(meta["token_id"], "10.0.0.5", client="Cursor 1.4", db_path=db)
    row = users_db.list_user_api_tokens(user["id"], db_path=db)[0]
    assert row["last_client"] == "Cursor 1.4" and row["last_used_ip"] == "10.0.0.5"


# --- MCP handshake ---


def test_client_label_is_short_and_printable():
    assert mcp.client_label({"name": "claude-code", "version": "2.1.0"}) == "claude-code 2.1.0"
    assert mcp.client_label({"name": "x", "title": "Claude Desktop"}) == "Claude Desktop"
    assert mcp.client_label({"name": "bad\x00\x1b[31m"}) == "bad[31m"
    assert mcp.client_label("nope") == "" and mcp.client_label({}) == ""
    assert len(mcp.client_label({"name": "n" * 500})) == 120


def test_initialize_remembers_the_client(monkeypatch):
    seen = []
    monkeypatch.setattr(
        users_db, "note_token_use", lambda token_id, ip="", client="", db_path=None: seen.append((token_id, client))
    )
    reply = mcp.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "Cursor", "version": "1.4"}},
        },
        _token_principal([]),
        "http://nas",
    )
    assert reply["result"]["serverInfo"]["name"] == "zettnas"
    assert seen == [("t1", "Cursor 1.4")]
    seen.clear()
    mcp.handle_message(
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}}, _token_principal([]), "http://nas"
    )
    assert seen == []
