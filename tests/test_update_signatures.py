"""In-app updates install only images signed by this project's CI."""

import base64
import hashlib
import json
import os

import httpx
import pytest

from backend.services import image_signature as sig

pytestmark = pytest.mark.real_signatures

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sigstore", "ci-bundle-d80d74eb.json")
DIGEST = "sha256:d80d74eb26ec2afb153a73cf649fb3a29408db6b6dd183b0e8782558468619dc"
OTHER = "sha256:" + "0" * 64


def _bundle() -> bytes:
    with open(FIXTURE, "rb") as f:
        return f.read()


@pytest.fixture(scope="module")
def verifier():
    from sigstore.verify import Verifier

    return Verifier.production(offline=True)  # the trust root shipped with sigstore; no network


def test_a_real_ci_signature_verifies(verifier):
    identity = sig.verify_bundle(_bundle(), DIGEST, verifier)
    assert identity == "https://github.com/fr0styx/zettnas-toolkit/.github/workflows/ci.yml@refs/heads/main"


def test_the_signature_must_name_this_digest(verifier):
    with pytest.raises(sig.SignatureError, match="different image"):
        sig.verify_bundle(_bundle(), OTHER, verifier)


def test_a_changed_statement_fails(verifier):
    bundle = json.loads(_bundle())
    env = bundle["dsseEnvelope"]
    statement = json.loads(base64.b64decode(env["payload"]))
    statement["subject"][0]["digest"]["sha256"] = OTHER.split(":")[1]
    env["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
    with pytest.raises(Exception):  # noqa: B017 - sigstore raises its own VerificationError
        sig.verify_bundle(json.dumps(bundle).encode(), OTHER, verifier)


@pytest.mark.parametrize(
    "uri, ok",
    [
        ("https://github.com/fr0styx/zettnas-toolkit/.github/workflows/ci.yml@refs/heads/main", True),
        ("https://github.com/fr0styx/zettnas-toolkit/.github/workflows/ci.yml@refs/tags/v1.9.4", True),
        ("https://github.com/fr0styx/zettnas-toolkit/.github/workflows/ci.yml@refs/heads/feature", False),
        ("https://github.com/fr0styx/zettnas-toolkit/.github/workflows/promote.yml@refs/heads/main", False),
        ("https://github.com/someone/zettnas-toolkit/.github/workflows/ci.yml@refs/heads/main", False),
        ("https://github.com/fr0styx/zettnas-toolkit/.github/workflows/ci.yml@refs/heads/main/x", False),
    ],
)
def test_only_this_projects_ci_on_main_or_a_version_tag(uri, ok):
    assert bool(sig.IDENTITY_RE.match(uri)) is ok


def _registry(bundle: bytes, *, referrers_api=False, corrupt=False, subject=DIGEST, extra=None):
    blob_digest = "sha256:" + hashlib.sha256(bundle).hexdigest()
    ref = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": "sha256:" + "a" * 64,
        # what cosign writes into GHCR's fallback index (the bundle type is only in the manifest)
        "artifactType": "application/vnd.oci.empty.v1+json",
    }
    others = extra or []
    manifest = {
        "artifactType": "application/vnd.dev.sigstore.bundle.v0.3+json",
        "layers": [
            {"mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json", "digest": blob_digest, "size": len(bundle)}
        ],
        "subject": {"digest": subject},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            return httpx.Response(200, json={"token": "t"})
        if "/referrers/" in path:
            return httpx.Response(200, json={"manifests": others + [ref]}) if referrers_api else httpx.Response(404)
        if path.endswith("/manifests/" + DIGEST.replace(":", "-")):
            return httpx.Response(200, json={"manifests": others + [ref]})
        if path.endswith("/manifests/" + ref["digest"]):
            return httpx.Response(200, json=manifest)
        if path.endswith("/blobs/" + blob_digest):
            return httpx.Response(200, content=bundle + (b" " if corrupt else b""))
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("referrers_api", [False, True])
def test_bundles_are_found_through_either_referrers_lookup(referrers_api):
    assert sig.fetch_bundles(DIGEST, _registry(_bundle(), referrers_api=referrers_api)) == [_bundle()]


def test_other_referrers_such_as_sboms_are_skipped():
    sbom = {
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "digest": "sha256:" + "b" * 64,
        "artifactType": "application/spdx+json",
    }
    assert sig.fetch_bundles(DIGEST, _registry(_bundle(), extra=[sbom])) == [_bundle()]


def test_live_registry_signature():
    """Against GHCR: a published build verifies (skipped without network)."""
    try:
        httpx.get("https://ghcr.io/token", timeout=5)
    except httpx.HTTPError:
        pytest.skip("no network")
    result = sig.verify_image(DIGEST)
    if result.reason.startswith(("could not download", "could not load")):
        pytest.skip(result.reason)  # the registry or Sigstore is unreachable; not this code
    assert result.ok, result.reason


def test_a_corrupted_download_is_rejected():
    with pytest.raises(sig.SignatureError, match="corrupted"):
        sig.fetch_bundles(DIGEST, _registry(_bundle(), corrupt=True))


def test_a_signature_for_another_image_is_ignored():
    assert sig.fetch_bundles(DIGEST, _registry(_bundle(), subject=OTHER)) == []


def test_verify_image_end_to_end(monkeypatch, verifier):
    monkeypatch.setattr(sig, "fetch_bundles", lambda d: [_bundle()])
    monkeypatch.setattr(sig, "_verifier", lambda: verifier)
    assert sig.verify_image(DIGEST).ok
    bad = sig.verify_image(OTHER)
    assert not bad.ok and "different image" in bad.reason
    monkeypatch.setattr(sig, "fetch_bundles", lambda d: [])
    assert sig.verify_image(DIGEST).reason == "the image has no signature"
    assert sig.verify_image("latest").reason == "no image digest to check"


@pytest.fixture
def update_env(client, auth_headers, monkeypatch):
    from backend.api import system

    async def _digest(tag):
        return DIGEST

    monkeypatch.setattr(system, "_registry_digest", _digest)
    monkeypatch.setattr("backend.services.container_mutator.pull_container_image", lambda *a, **k: None)
    monkeypatch.setattr(system, "_local_repo_digests", lambda ref: [DIGEST])
    monkeypatch.setattr(system, "docker_sock", lambda: "/nonexistent.sock")
    return client, auth_headers


@pytest.mark.parametrize(
    "mode, ok, status",
    [("enforce", True, 200), ("enforce", False, 502), ("warn", False, 200), ("off", False, 200)],
)
def test_update_endpoint_follows_the_signature_mode(update_env, monkeypatch, mode, ok, status):
    from backend import config

    client, headers = update_env
    calls = []

    def fake_verify(digest):
        calls.append(digest)
        return sig.SignatureResult(ok, "fine" if ok else "the image has no signature", "id" if ok else "")

    monkeypatch.setattr(config, "UPDATE_SIGNATURES", mode)
    monkeypatch.setattr(sig, "verify_image", fake_verify)
    r = client.post("/api/system/updates/apply", json={"channel": "stable"}, headers=headers)
    assert r.status_code == status, r.text
    assert calls == ([] if mode == "off" else [DIGEST])
    if status == 502:
        assert "signature" in r.json()["detail"]
    else:
        assert r.json()["signature"]["checked"] is (mode != "off")


def test_only_the_cosign_signature_statement_counts(verifier, monkeypatch):
    """SEC-37: a signed SBOM or scan about the same image is not a signature of it."""
    real = verifier.verify_dsse

    def other_predicate(bundle, policy):
        payload_type, payload = real(bundle, policy)
        statement = json.loads(payload)
        statement["predicateType"] = "https://spdx.dev/Document"
        return payload_type, json.dumps(statement).encode()

    monkeypatch.setattr(verifier, "verify_dsse", other_predicate)
    with pytest.raises(sig.SignatureError, match="unexpected signed statement"):
        sig.verify_bundle(_bundle(), DIGEST, verifier)
