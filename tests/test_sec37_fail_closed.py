"""SEC-37: search fails closed without a principal, the updater doesn't go back to an older
version unless asked to, and no stack or chat tool reaches Docker through its command line."""

import ast
import pathlib

import pytest

from backend import __version__
from backend.services.rag_engine_search import SYSTEM_PRINCIPAL, RagSearchMixin

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_search_without_a_principal_finds_nothing():
    assert RagSearchMixin._build_rbac_clause(None) == ("0", [])
    assert RagSearchMixin._build_rbac_clause(SYSTEM_PRINCIPAL) == ("1=1", [])


@pytest.fixture
def update_env(monkeypatch):
    from backend.api import system as sysapi

    monkeypatch.setattr("backend.services.container_mutator.pull_container_image", lambda ref, t=300.0: None)
    monkeypatch.setattr(sysapi, "docker_sock", lambda: "/nonexistent.sock")
    monkeypatch.setattr(sysapi, "_local_repo_digests", lambda ref: ["sha256:" + "a" * 64])

    async def served(tag):
        return "sha256:" + "a" * 64

    monkeypatch.setattr(sysapi, "_registry_digest", served)
    return sysapi


def test_older_than_running():
    from backend.api.system import older_than_running

    assert older_than_running("v0.0.1") and older_than_running("0.0.1")
    assert not older_than_running(f"v{__version__}")
    assert not older_than_running("v999.0.0")
    assert not older_than_running("main") and not older_than_running("edge") and not older_than_running("")


def test_an_older_tag_needs_a_revert(client, auth_headers, update_env):
    old = {"channel": "stable", "target_image": "ghcr.io/fr0styx/zettnas-toolkit:v0.0.1"}
    r = client.post("/api/system/updates/apply", json=old, headers=auth_headers)
    assert r.status_code == 409 and "revert" in r.json()["detail"]
    r = client.post("/api/system/updates/apply", json={**old, "revert": True}, headers=auth_headers)
    assert r.status_code == 200


def test_an_older_image_under_a_newer_name_is_refused(client, auth_headers, update_env, monkeypatch):
    monkeypatch.setattr(update_env, "_image_version_label", lambda ref: "0.0.1")
    r = client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers)
    assert r.status_code == 409 and "older" in r.json()["detail"]
    monkeypatch.setattr(update_env, "_image_version_label", lambda ref: "main")  # a build from main
    assert client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers).status_code == 200


@pytest.mark.parametrize("module", ["backend/services/docker_stacks.py", "backend/services/chat_nas_tools.py"])
def test_no_docker_command_line(module):
    tree = ast.parse((ROOT / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.List)
            and node.elts
            and isinstance(node.elts[0], ast.Constant)
            and node.elts[0].value == "docker"
        ):
            pytest.fail(f"{module}:{node.lineno} runs the docker command line; use the Docker API proxy")
