"""R4-1, the bridge: images go out as ghcr.io/fr0styx/kiboto and, until 2.2, under the old name too;
the updater accepts either name and a CI signature from the repository under either name."""

import asyncio
import pathlib

import pytest

from backend.api import system
from backend.services import image_signature as sig

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEW, OLD = "ghcr.io/fr0styx/kiboto", "ghcr.io/fr0styx/zettnas-toolkit"


def test_both_image_names_are_ours_and_nothing_else():
    for ref in (f"{NEW}:latest", f"{OLD}:latest", f"{NEW}@sha256:" + "a" * 64, f"{OLD}:sha-abc1234-core"):
        assert system._is_official_image_ref(ref), ref
    for ref in ("ghcr.io/fr0styx/kiboto-evil:latest", "ghcr.io/other/kiboto:latest", "docker.io/fr0styx/kiboto"):
        assert not system._is_official_image_ref(ref), ref
    assert system._repo_of(f"{OLD}:edge") == OLD and system._repo_of(f"{NEW}:edge") == NEW


def test_a_signature_from_either_repository_name_counts():
    tail = "/.github/workflows/ci.yml@refs/heads/main"
    assert sig.IDENTITY_RE.match("https://github.com/fr0styx/kiboto" + tail)
    assert sig.IDENTITY_RE.match("https://github.com/fr0styx/zettnas-toolkit" + tail)
    assert not sig.IDENTITY_RE.match("https://github.com/someone/kiboto" + tail)
    assert sig.REPOS == ("fr0styx/kiboto", "fr0styx/zettnas-toolkit")


@pytest.mark.parametrize("has, want", [({NEW, OLD}, NEW), ({OLD}, OLD), (set(), OLD), (None, OLD)])
def test_an_update_uses_the_new_name_once_it_has_the_tag(monkeypatch, has, want):
    async def digest_in(tag, image_repo):
        if has is None:  # the registry can't be asked
            raise OSError("offline")
        return "sha256:" + "a" * 64 if image_repo in has else None

    monkeypatch.setattr(system, "_registry_digest_in", digest_in)
    assert asyncio.run(system._image_with_tag("latest")) == f"{want}:latest"


def test_signatures_are_looked_for_under_either_name(monkeypatch):
    calls = []

    def fetch_in(digest, client, repo):
        calls.append(repo)
        if repo == "fr0styx/kiboto":
            raise OSError("no such package yet")
        return [b"bundle"]

    monkeypatch.setattr(sig, "_fetch_bundles_in", fetch_in)
    assert sig.fetch_bundles("sha256:" + "a" * 64) == [b"bundle"]
    assert calls == ["fr0styx/kiboto", "fr0styx/zettnas-toolkit"]
    monkeypatch.setattr(sig, "_fetch_bundles_in", lambda d, c, r: [])
    assert sig.fetch_bundles("sha256:" + "a" * 64) == []

    def broken(d, c, r):
        raise OSError("offline")

    monkeypatch.setattr(sig, "_fetch_bundles_in", broken)
    with pytest.raises(OSError):
        sig.fetch_bundles("sha256:" + "a" * 64)


def test_ci_publishes_and_signs_under_both_names():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "IMAGE: ghcr.io/fr0styx/kiboto" in ci and "OLD_IMAGE: ghcr.io/fr0styx/zettnas-toolkit" in ci
    assert ci.count("cosign sign --yes") == 2 and "ghcr.io/${{ github.repository }}" not in ci
