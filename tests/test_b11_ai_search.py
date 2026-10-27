"""B11 (AI-26): "AI search" and "Ask Zetty" are separate switches per role, both enforced;
upgraded installs keep AI search for kids and guests, with an Advisor fix; every kind is logged."""

import json
import os

import pytest

from backend.auth import AuthenticatedPrincipal
from backend.errors import ShownServerError
from backend.services import ai_access, install_defaults, safe_defaults_advisor
from backend.users_db import create_user


def who(role, name="someone"):
    return AuthenticatedPrincipal(user_id=name, username=name, role_id=role, scopes=["shares:read"])


@pytest.fixture
def cfg(monkeypatch):
    state = {"ai_role_access": {"kid": False, "guest": False}, "ai_search_role_access": {"kid": False, "guest": False}}

    class Engine:
        def get_config(self):
            return dict(state)

        def update_config(self, updates):
            for k, v in updates.items():
                state[k] = {**state.get(k, {}), **v}

    monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", lambda: Engine())
    return state


def test_search_and_ask_are_separate_switches(cfg):
    cfg["ai_search_role_access"] = {"kid": True}
    kid = who("kid")
    assert ai_access.allowed(kid, feature="search") and not ai_access.allowed(kid)
    cfg["ai_search_role_access"] = {}
    assert not ai_access.allowed(kid, feature="search")  # kids and guests start off
    assert ai_access.allowed(who("share_user"), feature="search")
    cfg["ai_search_role_access"] = {"superadmin": False}
    assert ai_access.allowed(who("superadmin"), feature="search")  # never locked out


def test_a_refused_search_is_logged_without_the_question(cfg):
    with pytest.raises(ShownServerError) as e:
        ai_access.require_ai_search(who("kid", "lea_s"))
    assert e.value.status_code == 403 and e.value.error == "ai_search_off_for_role"
    row = ai_access.recent(5, username="lea_s")[0]
    assert (row["kind"], row["outcome"]) == ("search", "refused")


def _login(client, username, role_id, password="GoodPass123!"):
    create_user(username, username, password, role_id=role_id)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def test_both_switches_are_enforced_on_the_routes(client):
    kid = _login(client, "ai_kid", "kid")
    res = client.get("/api/ai/search?q=cats", headers=kid)
    assert res.status_code == 403 and "AI search" in res.text
    res = client.post("/api/ai/ask", json={"query": "what are my bills"}, headers=kid)
    assert res.status_code == 403 and "Zetty" in res.text
    res = client.post("/api/ai/folder/audit", json={"folder_path": "/mnt/user"}, headers=kid)
    assert res.status_code == 403


def test_an_allowed_search_is_logged_as_a_search(client, monkeypatch):
    from backend.services import rag_engine

    monkeypatch.setattr(rag_engine.RagSearchEngine, "search", lambda self, *a, **k: {"results": []})
    headers = _login(client, "ai_parent", "share_user")
    res = client.get("/api/ai/search?q=cats", headers=headers)
    assert res.status_code == 200, res.text
    row = ai_access.recent(5, username="ai_parent")[0]
    assert (row["kind"], row["outcome"]) == ("search", "answered")


def test_the_api_saves_the_search_switch_alone(client, auth_headers):
    res = client.put("/api/ai/access", json={"search_roles": {"kid": True}}, headers=auth_headers)
    assert res.status_code == 200, res.text
    kid = next(r for r in res.json()["roles"] if r["id"] == "kid")
    assert kid["search"] is True and kid["on"] is False


# --- upgraded installs keep AI search for kids and guests --------------------------------------


def _read(path):
    with open(path) as f:
        return json.load(f)


def _fresh(existing):
    from backend.services.rag_engine import RAG_CONFIG_PATH

    for path in (install_defaults._marker(), RAG_CONFIG_PATH):
        if os.path.exists(path):
            os.remove(path)
    install_defaults.apply_once(existing)
    return RAG_CONFIG_PATH


def test_an_upgraded_install_keeps_ai_search_for_kids_once():
    path = _fresh(existing=True)
    assert install_defaults.apply_steps() == ["ai_search"]
    assert _read(path)["ai_search_role_access"] == {"kid": True, "guest": True}
    assert install_defaults.apply_steps() == []  # once
    marker = _read(install_defaults._marker())
    assert marker["steps"] == ["ai_search"] and marker["existing"] is True


def test_an_upgraded_install_keeps_a_choice_already_made():
    path = _fresh(existing=True)
    with open(path, "w") as f:
        json.dump({"ai_search_role_access": {"kid": False}}, f)
    install_defaults.apply_steps()
    assert _read(path)["ai_search_role_access"] == {"kid": False}


def test_a_new_install_only_records_the_step():
    path = _fresh(existing=False)
    assert install_defaults.apply_steps() == ["ai_search"]
    assert not os.path.exists(path)


def test_no_marker_no_steps():
    if os.path.exists(install_defaults._marker()):
        os.remove(install_defaults._marker())
    assert install_defaults.apply_steps() == []


def test_the_advisor_offers_to_turn_ai_search_off(cfg, monkeypatch):
    monkeypatch.setattr(safe_defaults_advisor, "_family_users", lambda: ["lea"])
    cfg["ai_search_role_access"] = {"kid": True, "guest": False}
    assert "ai_search_family" in {f["id"] for f in safe_defaults_advisor.findings()}
    assert "off" in safe_defaults_advisor.apply_fix("ai_search_family")
    assert cfg["ai_search_role_access"] == {"kid": False, "guest": False}
    assert "ai_search_family" not in {f["id"] for f in safe_defaults_advisor.findings()}
    monkeypatch.setattr(safe_defaults_advisor, "_family_users", lambda: [])
    cfg["ai_search_role_access"] = {"kid": True}
    assert "ai_search_family" not in {f["id"] for f in safe_defaults_advisor.findings()}
