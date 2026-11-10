"""RES-3: passkeys with a software authenticator (an ES256 key) speaking real WebAuthn messages."""

import os

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import sha256, websafe_decode, websafe_encode
from fido2.webauthn import (
    Aaguid,
    AttestationObject,
    AttestedCredentialData,
    AuthenticatorData,
    CollectedClientData,
)

from backend.services import passkeys

HOST = "attic.example-tailnet.ts.net"
ORIGIN = f"https://{HOST}"


class FakeAuthenticator:
    """What a phone or a security key does, without the hardware."""

    def __init__(self, rp_id=HOST, origin=ORIGIN):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.rp_id, self.origin, self.count, self.user = rp_id, origin, 0, b""
        self.uv = True

    def _flags(self, attested=False):
        f = AuthenticatorData.FLAG.UP
        if self.uv:
            f |= AuthenticatorData.FLAG.UV
        if attested:
            f |= AuthenticatorData.FLAG.AT
        return f

    def create(self, options):
        pk = options["publicKey"]
        self.user = websafe_decode(pk["user"]["id"])
        client = CollectedClientData.create(
            type="webauthn.create", challenge=websafe_decode(pk["challenge"]), origin=self.origin
        )
        cred = AttestedCredentialData.create(
            Aaguid.NONE, self.cred_id, ES256.from_cryptography_key(self.key.public_key())
        )
        auth = AuthenticatorData.create(sha256(self.rp_id.encode()), self._flags(True), 0, cred)
        att = AttestationObject.create("none", auth, {})
        cid = websafe_encode(self.cred_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {"clientDataJSON": websafe_encode(client), "attestationObject": websafe_encode(att)},
            "clientExtensionResults": {},
        }

    def get(self, options):
        pk = options["publicKey"]
        client = CollectedClientData.create(
            type="webauthn.get", challenge=websafe_decode(pk["challenge"]), origin=self.origin
        )
        self.count += 1
        auth = AuthenticatorData.create(sha256(self.rp_id.encode()), self._flags(), self.count)
        sig = self.key.sign(bytes(auth) + sha256(bytes(client)), ec.ECDSA(hashes.SHA256()))
        cid = websafe_encode(self.cred_id)
        return {
            "id": cid,
            "rawId": cid,
            "type": "public-key",
            "response": {
                "clientDataJSON": websafe_encode(client),
                "authenticatorData": websafe_encode(auth),
                "signature": websafe_encode(sig),
                "userHandle": websafe_encode(self.user),
            },
            "clientExtensionResults": {},
        }


@pytest.fixture
def ann():
    from backend.users_db import create_user, get_user_by_username

    if not get_user_by_username("pk_ann"):
        create_user("pk_ann", "Ann", "a-long-password-1", role_id="share_user")
    user = get_user_by_username("pk_ann")
    passkeys.forget_user(user["id"])
    return user


def _add(user, device, name="Phone"):
    opts = passkeys.register_options(user, HOST)
    return passkeys.register_finish(user, opts["ticket"], device.create(opts["options"]), name)


def test_add_a_passkey_and_sign_in_with_it_alone(ann):
    phone = FakeAuthenticator()
    added = _add(ann, phone, "  Ann's phone  ")
    assert added["name"] == "Ann's phone"
    [listed] = passkeys.list_for(ann["id"])
    assert listed["rp_id"] == HOST and listed["last_used_at"] is None
    assert passkeys.has_passkeys(ann["id"])

    opts = passkeys.login_options(HOST, extra={"remember_me": True})
    assert (
        "allowCredentials" not in opts["options"]["publicKey"] or not opts["options"]["publicKey"]["allowCredentials"]
    )
    uid, extra = passkeys.login_finish(opts["ticket"], phone.get(opts["options"]))
    assert uid == ann["id"] and extra == {"remember_me": True}
    assert passkeys.list_for(ann["id"])[0]["last_used_at"]


def test_as_the_second_step_only_the_persons_own_passkeys_count(ann):
    from backend.users_db import create_user, get_user_by_username

    if not get_user_by_username("pk_bob"):
        create_user("pk_bob", "Bob", "another-long-pass-2", role_id="share_user")
    bob = get_user_by_username("pk_bob")
    passkeys.forget_user(bob["id"])
    anns, bobs = FakeAuthenticator(), FakeAuthenticator()
    _add(ann, anns)
    _add(bob, bobs)
    opts = passkeys.login_options(HOST, ann["id"])
    allowed = [c["id"] for c in opts["options"]["publicKey"]["allowCredentials"]]
    assert allowed == [websafe_encode(anns.cred_id)]
    with pytest.raises(passkeys.PasskeyError, match="isn't known"):
        passkeys.login_finish(opts["ticket"], bobs.get(opts["options"]))
    with pytest.raises(passkeys.PasskeyError, match="no passkey"):
        passkeys.login_options(HOST, "nobody-id")


def test_a_ticket_is_used_once_and_only_for_its_kind(ann):
    phone = FakeAuthenticator()
    _add(ann, phone)
    opts = passkeys.login_options(HOST)
    answer = phone.get(opts["options"])
    passkeys.login_finish(opts["ticket"], answer)
    with pytest.raises(passkeys.PasskeyError, match="expired"):
        passkeys.login_finish(opts["ticket"], answer)  # a replay
    reg = passkeys.register_options(ann, HOST)
    with pytest.raises(passkeys.PasskeyError, match="expired"):
        passkeys.login_finish(reg["ticket"], answer)


def test_a_wrong_signature_another_site_or_no_user_verification_fails(ann):
    phone = FakeAuthenticator()
    _add(ann, phone)
    opts = passkeys.login_options(HOST)
    answer = phone.get(opts["options"])
    answer["response"]["signature"] = websafe_encode(b"\x30\x06\x02\x01\x01\x02\x01\x01")
    with pytest.raises(passkeys.PasskeyError, match="signature"):
        passkeys.login_finish(opts["ticket"], answer)

    phishing = FakeAuthenticator(origin="https://attic.example-tailnet.ts.net.evil.example")
    phishing.key, phishing.cred_id = phone.key, phone.cred_id
    opts = passkeys.login_options(HOST)
    with pytest.raises(passkeys.PasskeyError):
        passkeys.login_finish(opts["ticket"], phishing.get(opts["options"]))

    phone.uv = False
    opts = passkeys.login_options(HOST)
    with pytest.raises(passkeys.PasskeyError):
        passkeys.login_finish(opts["ticket"], phone.get(opts["options"]))


def test_an_ip_address_or_plain_http_is_refused(ann):
    for host in ("192.168.50.10:8082", "[::1]:8082", ""):
        with pytest.raises(passkeys.PasskeyError, match="not an IP"):
            passkeys.rp_id_for(host)
    assert passkeys.rp_id_for("Attic.Example-Tailnet.ts.net:443") == HOST
    plain = FakeAuthenticator(origin=f"http://{HOST}")
    opts = passkeys.register_options(ann, HOST)
    with pytest.raises(passkeys.PasskeyError, match="could not be checked"):
        passkeys.register_finish(ann, opts["ticket"], plain.create(opts["options"]))
    local = FakeAuthenticator(rp_id="localhost", origin="http://localhost:8082")
    opts = passkeys.register_options(ann, "localhost:8082")
    assert passkeys.register_finish(ann, opts["ticket"], local.create(opts["options"]))["name"] == "Passkey"


def test_rename_remove_and_someone_elses_ticket(ann):
    phone = FakeAuthenticator()
    pk = _add(ann, phone)
    assert passkeys.rename(ann["id"], pk["id"], "Work key")
    assert passkeys.list_for(ann["id"])[0]["name"] == "Work key"
    with pytest.raises(passkeys.PasskeyError, match="name"):
        passkeys.rename(ann["id"], pk["id"], "  ")
    opts = passkeys.register_options(ann, HOST)
    with pytest.raises(passkeys.PasskeyError, match="already added"):
        passkeys.register_finish(ann, opts["ticket"], phone.create(opts["options"]))
    opts = passkeys.register_options(ann, HOST)
    with pytest.raises(passkeys.PasskeyError, match="someone else"):
        passkeys.register_finish({**ann, "id": "other"}, opts["ticket"], FakeAuthenticator().create(opts["options"]))
    assert passkeys.delete(ann["id"], pk["id"]) and not passkeys.has_passkeys(ann["id"])
    assert not passkeys.delete(ann["id"], pk["id"])


def test_the_routes(client, auth_headers):
    """Signed-in routes need a person; the sign-in routes are public but checked."""
    res = client.post("/api/auth/passkey/login/options", json={}, headers={"host": HOST})
    assert res.status_code == 200 and res.json()["ticket"]
    res = client.post("/api/auth/passkey/login/options", json={}, headers={"host": "192.168.50.10:8082"})
    assert res.status_code == 400 and "IP address" in res.json()["detail"]
    res = client.post("/api/auth/passkey/login", json={"ticket": "x" * 20, "credential": {"id": "AAAA"}})
    assert res.status_code == 401
    res = client.post("/api/auth/passkey/login/options", json={"mfa_token": "mfa_bogus.x"}, headers={"host": HOST})
    assert res.status_code == 401


def test_the_password_step_offers_the_passkey(client, ann):
    """Someone with a passkey and no code gets the second step with the passkey offered."""
    _add(ann, FakeAuthenticator())
    res = client.post("/api/auth/login", json={"username": "pk_ann", "password": "a-long-password-1"})
    body = res.json()
    assert body["status"] == "mfa_required" and body["passkey"] is True and body["code"] is False
    opts = client.post(
        "/api/auth/passkey/login/options", json={"mfa_token": body["mfa_token"]}, headers={"host": HOST}
    ).json()
    assert [c["type"] for c in opts["options"]["publicKey"]["allowCredentials"]] == ["public-key"]


def test_a_passkey_counts_for_a_role_that_requires_two_step(ann, monkeypatch):
    from backend.services import mfa_policy

    monkeypatch.setattr(mfa_policy, "required_roles", lambda: {"share_user"})
    assert mfa_policy.account_needs_setup(ann)
    _add(ann, FakeAuthenticator())
    assert not mfa_policy.account_needs_setup(ann)


def test_an_administrator_can_remove_someones_passkeys(client, auth_headers, ann):
    _add(ann, FakeAuthenticator())
    res = client.delete(f"/api/users/{ann['id']}/passkeys", headers=auth_headers)
    assert res.status_code == 200 and res.json() == {"removed": 1}
    assert not passkeys.has_passkeys(ann["id"])
    assert client.delete("/api/users/nobody/passkeys", headers=auth_headers).status_code == 404
