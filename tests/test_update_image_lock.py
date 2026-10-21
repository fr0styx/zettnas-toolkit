"""The in-app updater installs only this project's images."""

import pytest

from backend.api import system


@pytest.mark.parametrize(
    "ref,ok",
    [
        ("ghcr.io/fr0styx/zettnas-toolkit:latest", True),
        ("ghcr.io/fr0styx/zettnas-toolkit:1.9.2", True),
        ("ghcr.io/fr0styx/zettnas-toolkit@sha256:" + "a" * 64, True),
        ("ghcr.io/fr0styx/zettnas-toolkit-evil:latest", False),
        ("ghcr.io/attacker/zettnas-toolkit:latest", False),
        ("docker.io/library/alpine:latest", False),
        ("ghcr.io/fr0styx/zettnas-toolkit:latest;rm -rf /", False),
    ],
)
def test_official_image_refs(ref, ok):
    assert system._is_official_image_ref(ref) is ok


def test_apply_refuses_foreign_image_and_unverified_pull(client, auth_headers, monkeypatch):
    res = client.post(
        "/api/system/updates/apply",
        json={"channel": "stable", "target_image": "docker.io/attacker/backdoor:latest"},
        headers=auth_headers,
    )
    assert res.status_code == 400

    monkeypatch.setattr("backend.services.container_mutator.pull_container_image", lambda *a, **k: None)
    monkeypatch.setattr(system, "_local_repo_digests", lambda ref: [])
    spawned = []
    monkeypatch.setattr("backend.services.self_updater.spawn_self_updater", lambda *a, **k: spawned.append(a) or True)
    res = client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=auth_headers)
    assert res.status_code == 502 and not spawned
