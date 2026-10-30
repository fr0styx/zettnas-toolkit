"""Container details and compose files hide secrets; only callers who manage containers may
ask to see them (a read-only account asking for them still gets them masked)."""

import pytest

from backend.services import compose_synthesizer
from backend.users_db import create_user


@pytest.fixture
def seen(monkeypatch):
    calls = []

    def details(cid, allow_unmasked=False):
        calls.append(("details", cid, allow_unmasked))
        return {"id": cid, "env": ["DB_PASSWORD=" + ("hunter2" if allow_unmasked else "********")]}

    def compose(cid, allow_unmasked=False):
        calls.append(("compose", cid, allow_unmasked))
        return {"yaml": "x"} if cid != "gone" else {"error": "No such container"}

    monkeypatch.setattr(compose_synthesizer, "get_container_full_details", details)
    monkeypatch.setattr(compose_synthesizer, "get_container_compose_data", compose)
    return calls


def _token_for(client, username, role):
    create_user(username=username, display_name=username, password="Auditor-Pass-123", role_id=role)
    r = client.post("/api/auth/login", json={"username": username, "password": "Auditor-Pass-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_managers_can_unmask(client, auth_headers, seen):
    r = client.get("/api/docker/containers/web/details?unmask=true", headers=auth_headers)
    assert r.status_code == 200 and seen[-1] == ("details", "web", True)
    client.get("/api/docker/containers/web/compose?unmask=true", headers=auth_headers)
    assert seen[-1] == ("compose", "web", True)
    client.get("/api/docker/containers/web/details", headers=auth_headers)
    assert seen[-1] == ("details", "web", False)  # masked unless asked


def test_a_read_only_account_never_gets_secrets(client, seen):
    headers = _token_for(client, "auditor1", "auditor")
    r = client.get("/api/docker/containers/web/details?unmask=true", headers=headers)
    assert r.status_code == 200 and seen[-1] == ("details", "web", False)
    assert "hunter2" not in r.text
    r = client.get("/api/docker/containers/web/compose?unmask=true", headers=headers)
    assert r.status_code == 403 and seen[-1] == ("details", "web", False)  # compose needs containers:read (NSEC-16)


@pytest.mark.parametrize("cid", ["bad id", "a;b", "x" * 129])
def test_container_ids_are_checked(client, auth_headers, seen, cid):
    from urllib.parse import quote

    for path in ("details", "compose"):
        assert client.get(f"/api/docker/containers/{quote(cid)}/{path}", headers=auth_headers).status_code == 400
    assert seen == []


def test_missing_container(client, auth_headers, seen):
    assert client.get("/api/docker/containers/gone/compose", headers=auth_headers).status_code == 404


def test_recreate_and_ports_report_errors(client, auth_headers, monkeypatch):
    from backend.services import container_mutator

    def bad(*a, **k):
        raise ValueError("port 80 is taken")

    def broken(*a, **k):
        raise RuntimeError("docker down")

    monkeypatch.setattr(container_mutator, "recreate_container_ports", bad)
    r = client.post("/api/docker/containers/web/ports", json={"ports": []}, headers=auth_headers)
    assert r.status_code == 400 and "taken" in r.json()["detail"]
    monkeypatch.setattr(container_mutator, "recreate_container", broken)
    assert client.post("/api/docker/containers/web/recreate", json={}, headers=auth_headers).status_code == 500
    seen = {}
    monkeypatch.setattr(container_mutator, "recreate_container", lambda **kw: seen.update(kw) or {"status": "ok"})
    r = client.post(
        "/api/docker/containers/web/recreate", json={"image": "nginx:1.27", "env": ["A=1"]}, headers=auth_headers
    )
    assert (
        r.json() == {"status": "ok"}
        and seen["cid"] == "web"
        and seen["image"] == "nginx:1.27"
        and seen["port_bindings"] is None
    )
