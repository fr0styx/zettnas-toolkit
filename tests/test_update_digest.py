"""OPS-18: the image digest, not the version string, decides whether an update exists."""

import pytest

from backend.api import system


@pytest.fixture
def version_says(monkeypatch):
    def set_result(update_available, channel="stable"):
        async def fake(force=False, channel_arg=None, **kw):
            return {"channel": channel, "update_available": update_available, "latest_version": "9.9.9"}

        monkeypatch.setattr(system, "_check_system_updates_by_version", lambda force=False, channel="stable": fake())

    return set_result


def _digests(monkeypatch, remote, local):
    async def fake_remote(tag):
        return remote

    monkeypatch.setattr(system, "_registry_digest", fake_remote)
    monkeypatch.setattr(system, "_running_repo_digests", lambda: local)


async def test_same_digest_means_no_update_even_if_a_newer_version_is_announced(version_says, monkeypatch):
    version_says(True, channel="edge")
    _digests(monkeypatch, "sha256:aaa", ["sha256:aaa"])
    res = await system.check_system_updates(channel="edge")
    assert res["update_available"] is False and res["update_basis"] == "digest" and "not published" in res["note"]


async def test_different_digest_means_update(version_says, monkeypatch):
    version_says(False)
    _digests(monkeypatch, "sha256:bbb", ["sha256:aaa"])
    res = await system.check_system_updates()
    assert res["update_available"] is True and res["update_basis"] == "digest"


async def test_unknown_digest_falls_back_to_the_version_check(version_says, monkeypatch):
    version_says(True)
    _digests(monkeypatch, "sha256:bbb", [])  # locally built image: no registry digest
    res = await system.check_system_updates()
    assert res["update_available"] is True and res["update_basis"] == "version"
