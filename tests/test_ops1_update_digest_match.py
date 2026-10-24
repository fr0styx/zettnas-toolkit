"""The image the updater installs is the one the registry served when the update started (OPS-1)."""

import pytest


@pytest.fixture
def update_env(monkeypatch):
    from backend.api import system as sysapi

    monkeypatch.setattr("backend.services.container_mutator.pull_container_image", lambda ref, t=300.0: None)
    monkeypatch.setattr(sysapi, "docker_sock", lambda: "/nonexistent.sock")  # don't spawn the helper
    return sysapi


def _apply(client, auth_headers):
    return client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers)


def test_a_moved_tag_is_refused(client, auth_headers, update_env, monkeypatch):
    async def served(tag):
        return "sha256:" + "a" * 64

    monkeypatch.setattr(update_env, "_registry_digest", served)
    monkeypatch.setattr(update_env, "_local_repo_digests", lambda ref: ["sha256:" + "b" * 64])
    r = _apply(client, auth_headers)
    assert r.status_code == 409 and "changed while it was downloading" in r.json()["detail"]


def test_the_served_image_is_accepted(client, auth_headers, update_env, monkeypatch):
    async def served(tag):
        return "sha256:" + "a" * 64

    monkeypatch.setattr(update_env, "_registry_digest", served)
    monkeypatch.setattr(update_env, "_local_repo_digests", lambda ref: ["sha256:" + "a" * 64])
    r = _apply(client, auth_headers)
    assert r.status_code == 200 and r.json()["status"] == "pulled"
