"""
Checks that an update image was signed by this project's CI before it is installed.

CI signs every image digest with cosign, keyless: the signature is a Sigstore bundle
(a DSSE envelope holding an in-toto statement about the digest) with a short-lived
certificate issued to the CI workflow and an entry in the public transparency log.
cosign stores it next to the image as an OCI referrer; GHCR has no referrers API, so
it sits under the fallback tag ``sha256-<digest>``.

An image passes when a bundle for it
- verifies against the Sigstore trust root (certificate chain, transparency log entry),
- was issued by GitHub Actions to .github/workflows/ci.yml of this repository, on main
  or a version tag (the same identity the release notes tell people to check), and
- names exactly this digest as its subject.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass

import httpx

from backend.config import logger

REPO = "fr0styx/zettnas-toolkit"
REGISTRY = "https://ghcr.io"
ISSUER = "https://token.actions.githubusercontent.com"
IDENTITY_RE = re.compile(
    r"^https://github\.com/fr0styx/zettnas-toolkit/\.github/workflows/ci\.yml@refs/(heads/main|tags/v[0-9][^/\s]*)$"
)
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_BUNDLE_PREFIX = "application/vnd.dev.sigstore.bundle"
_INDEX = "application/vnd.oci.image.index.v1+json"
_MANIFEST = "application/vnd.oci.image.manifest.v1+json"
_EMPTY = "application/vnd.oci.empty.v1+json"
_MAX_BUNDLE_BYTES = 1 << 20
_MAX_REFERRERS = 16
_VERIFIER_TTL_S = 6 * 3600


class SignatureError(Exception):
    """The image has no valid signature from this project's CI."""


@dataclass
class SignatureResult:
    ok: bool
    reason: str
    identity: str = ""

    def as_dict(self) -> dict:
        return {"verified": self.ok, "reason": self.reason, "identity": self.identity}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _token(client: httpx.Client) -> str:
    r = client.get(f"{REGISTRY}/token", params={"scope": f"repository:{REPO}:pull"})
    r.raise_for_status()
    token = r.json().get("token")
    if not token:
        raise SignatureError("the registry gave no pull token")
    return token


def _manifests_referring_to(client: httpx.Client, headers: dict, digest: str) -> list[dict]:
    """Referrer manifests of a digest: the referrers API, else cosign's fallback tag."""
    r = client.get(f"{REGISTRY}/v2/{REPO}/referrers/{digest}", headers={**headers, "Accept": _INDEX})
    if r.status_code == 200:
        found = r.json().get("manifests") or []
        if found:
            return found
    r = client.get(f"{REGISTRY}/v2/{REPO}/manifests/{digest.replace(':', '-')}", headers={**headers, "Accept": _INDEX})
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json().get("manifests") or []


def fetch_bundles(digest: str, client: httpx.Client | None = None) -> list[bytes]:
    """The Sigstore bundles stored for an image digest (each checked against its blob digest)."""
    own = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        headers = {"Authorization": f"Bearer {_token(client)}"}
        bundles = []
        for ref in _manifests_referring_to(client, headers, digest)[:_MAX_REFERRERS]:
            # In cosign's fallback index the entry's type is often "empty"; the bundle type is in the manifest
            ref_type = str(ref.get("artifactType", ""))
            if ref_type and not ref_type.startswith(_BUNDLE_PREFIX) and ref_type != _EMPTY:
                continue
            ref_digest = str(ref.get("digest", ""))
            if not _DIGEST_RE.match(ref_digest):
                continue
            r = client.get(
                f"{REGISTRY}/v2/{REPO}/manifests/{ref_digest}",
                headers={**headers, "Accept": ref.get("mediaType") or _MANIFEST},
            )
            r.raise_for_status()
            manifest = r.json()
            if (manifest.get("subject") or {}).get("digest") not in (None, digest):
                continue
            for layer in manifest.get("layers") or []:
                blob_digest = str(layer.get("digest", ""))
                if not str(layer.get("mediaType", "")).startswith(_BUNDLE_PREFIX) or not _DIGEST_RE.match(blob_digest):
                    continue
                if int(layer.get("size") or 0) > _MAX_BUNDLE_BYTES:
                    continue
                b = client.get(f"{REGISTRY}/v2/{REPO}/blobs/{blob_digest}", headers=headers)
                b.raise_for_status()
                if "sha256:" + hashlib.sha256(b.content).hexdigest() != blob_digest:
                    raise SignatureError("a signature download was corrupted")
                bundles.append(b.content)
        return bundles
    finally:
        if own:
            client.close()


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _san_uris(cert) -> list[str]:
    from cryptography import x509

    try:
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return []
    return san.get_values_for_type(x509.UniformResourceIdentifier)


class CiIdentity:
    """Sigstore policy: issued by GitHub Actions to this repository's CI workflow (main or a version tag)."""

    def verify(self, cert) -> None:
        from sigstore.errors import VerificationError
        from sigstore.verify import policy

        policy.OIDCIssuerV2(ISSUER).verify(cert)
        uris = _san_uris(cert)
        if not any(IDENTITY_RE.match(u) for u in uris):
            raise VerificationError(f"signed by {', '.join(uris) or 'an unknown identity'}, not this project's CI")


_verifier_lock = threading.Lock()
_verifier_cache: dict = {"verifier": None, "at": 0.0}


def _verifier():
    """The Sigstore verifier, refreshed every few hours; the built-in trust root when offline."""
    from sigstore.verify import Verifier

    with _verifier_lock:
        if _verifier_cache["verifier"] is not None and time.time() - _verifier_cache["at"] < _VERIFIER_TTL_S:
            return _verifier_cache["verifier"]
        try:
            verifier = Verifier.production()
        except Exception as exc:
            logger.warning(f"[Update] Could not refresh the Sigstore trust root ({exc}); using the built-in copy.")
            verifier = Verifier.production(offline=True)
        _verifier_cache.update(verifier=verifier, at=time.time())
        return verifier


STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://sigstore.dev/cosign/sign/v1"


def verify_bundle(bundle_json: bytes, digest: str, verifier=None) -> str:
    """Verifies one bundle for a digest. Returns the signer identity; raises on any problem."""
    from sigstore.models import Bundle

    bundle = Bundle.from_json(bundle_json)
    payload_type, payload = (verifier or _verifier()).verify_dsse(bundle, CiIdentity())
    if payload_type != "application/vnd.in-toto+json":
        raise SignatureError(f"unexpected signed content ({payload_type})")
    statement = json.loads(payload)
    # SEC-37: only the statement `cosign sign` makes; another signed claim about the same image
    # (an SBOM, a scan result) is not a signature of the image
    if statement.get("_type") != STATEMENT_TYPE or statement.get("predicateType") != PREDICATE_TYPE:
        raise SignatureError(f"unexpected signed statement ({statement.get('predicateType')})")
    want = digest.split(":", 1)[1]
    if not any((s.get("digest") or {}).get("sha256") == want for s in statement.get("subject") or []):
        raise SignatureError("the signature is for a different image")
    uris = _san_uris(bundle.signing_certificate)
    return uris[0] if uris else ""


def verify_image(digest: str) -> SignatureResult:
    """Whether CI signed this image digest. Never raises."""
    if not _DIGEST_RE.match(str(digest or "")):
        return SignatureResult(False, "no image digest to check")
    try:
        bundles = fetch_bundles(digest)
    except Exception as exc:
        return SignatureResult(False, f"could not download the signature ({exc})")
    if not bundles:
        return SignatureResult(False, "the image has no signature")
    try:
        verifier = _verifier()
    except Exception as exc:
        return SignatureResult(False, f"could not load the Sigstore trust root ({exc})")
    problems = []
    for bundle_json in bundles:
        try:
            identity = verify_bundle(bundle_json, digest, verifier)
            return SignatureResult(True, "signed by this project's CI", identity)
        except Exception as exc:
            problems.append(str(exc) or type(exc).__name__)
    return SignatureResult(False, "the signature did not verify: " + "; ".join(problems))
