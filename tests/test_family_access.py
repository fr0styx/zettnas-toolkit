"""NFEAT-1: each family member's own way in from outside, through a Tailscale share of the NAS alone."""

import io
import json
import time
import urllib.error

import pytest

from backend.services import family_access as fa
from backend.services import remote_access

# a made-up key, built in pieces so secret scanning doesn't take it for a real one
KEY = "-".join(["tskey", "api", "kAbc123CNTRL", "SecretPart12345678"])
DOC = {
    "Self": {"ID": "nTestNode1CNTRL", "DNSName": "attic.example-tailnet.ts.net."},
    "Peer": {
        "a": {"UserID": 7, "Online": True},
        "b": {"UserID": 8, "Online": False},
    },
    "User": {"7": {"LoginName": "Gran@Example.com"}, "8": {"LoginName": "kid@example.com"}},
}


class FakeTailscale:
    """Tailscale's API: invites per device, a key with an expiry, and who accepted what."""

    def __init__(self):
        self.calls = []
        self.invites = {}
        self.refuse = False
        self.made = 0

    def __call__(self, req, timeout=10):
        method, url = req.get_method(), req.full_url
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, url.removeprefix(fa.API), body, req.get_header("Authorization")))
        if self.refuse:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad key"}'))
        path = url.removeprefix(fa.API)
        if path.startswith("/tailnet/-/keys/"):
            return self._reply({"id": "kAbc123CNTRL", "expires": "2027-01-01T00:00:00Z"})
        if path == "/device/nTestNode1CNTRL/device-invites" and method == "GET":
            return self._reply(list(self.invites.values()))
        if path == "/device/nTestNode1CNTRL/device-invites" and method == "POST":
            n = str(100 + self.made)
            self.made += 1
            self.invites[n] = {
                "id": n,
                "inviteUrl": f"https://login.tailscale.com/admin/invite/code{n}",
                "accepted": False,
            }
            return self._reply([self.invites[n]])
        if path.startswith("/device-invites/") and method == "GET":
            return self._reply(self.invites[path.rsplit("/", 1)[1]])
        if path.startswith("/device-invites/") and method == "DELETE":
            self.invites.pop(path.rsplit("/", 1)[1], None)
            return self._reply(None)
        raise AssertionError(f"unexpected {method} {path}")

    @staticmethod
    def _reply(doc):
        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(b"" if doc is None else json.dumps(doc).encode())


@pytest.fixture
def api(tmp_path, monkeypatch):
    fake = FakeTailscale()
    monkeypatch.setattr(fa, "STATE_FILE", str(tmp_path / "family_access.json"))
    monkeypatch.setattr(fa, "_tailscale", lambda: DOC)
    monkeypatch.setattr(fa, "_on_headscale", lambda: False)
    monkeypatch.setattr(fa, "_NO_REDIRECTS", type("O", (), {"open": staticmethod(fake)})())
    monkeypatch.setattr(fa, "_audit", lambda *a: fake.calls.append(("audit", *a)))
    monkeypatch.setattr(fa, "REFRESH_EVERY", 0.0)
    monkeypatch.setattr(
        fa, "page_url", lambda token: f"https://attic.example-tailnet.ts.net:8443{fa.PAGE_PATH}/{token}"
    )
    monkeypatch.setattr(
        remote_access, "status", lambda: {"addresses": {"kiboto": "https://attic.example-tailnet.ts.net/"}}
    )
    return fake


def _token(user_id="u1"):
    return next(t for t, i in fa._state()["invites"].items() if i["user_id"] == user_id)


def test_the_key_is_checked_sealed_and_its_expiry_read(api, tmp_path):
    with pytest.raises(fa.FamilyAccessError, match="tskey-api-"):
        fa.save_key("not-a-key")
    st = fa.save_key(KEY, "admin")
    assert st["has_key"] and st["key_days_left"] is not None
    raw = (tmp_path / "family_access.json").read_text()
    assert KEY not in raw  # kept sealed
    assert api.calls[0][:2] == ("GET", "/device/nTestNode1CNTRL/device-invites")
    assert api.calls[0][3] == f"Bearer {KEY}"
    api.refuse = True
    with pytest.raises(fa.FamilyAccessError, match="didn't accept the API key"):
        fa.save_key(KEY)
    assert not fa.forget_key()["has_key"]


def test_days_left_and_the_warning():
    now = time.time()
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 10 * 86400 + 60))
    assert fa.days_left(soon, now) == 10
    assert fa.days_left("", now) is None and fa.days_left("garbage", now) is None


def test_an_invite_is_single_use_and_replaces_an_open_one(api):
    with pytest.raises(fa.FamilyAccessError, match="API access key first"):
        fa.invite("u1", "gran", "Gran")
    fa.save_key(KEY)
    st = fa.invite("u1", "gran", "Gran", "admin")
    posts = [c for c in api.calls if c[0] == "POST"]
    assert posts[0][2] == [{"multiUse": False, "allowExitNode": False}]
    gran = st["people"][0]
    assert gran["state"] == "invited" and gran["invite_url"].endswith("code100")
    assert gran["page_url"].endswith(_token())
    fa.invite("u1", "gran", "Gran")
    assert ("DELETE", "/device-invites/100", None, f"Bearer {KEY}") in api.calls
    assert len(fa.status()["people"]) == 1


def test_accepting_shows_joined_then_online(api):
    fa.save_key(KEY)
    fa.invite("u1", "gran", "Gran")
    fa.invite("u2", "kid", "Kid")
    api.invites["100"].update(accepted=True, acceptedBy={"loginName": "gran@example.com"})
    api.invites["101"].update(accepted=True, acceptedBy={"loginName": "kid@example.com"})
    fa.refresh()
    people = {p["username"]: p for p in fa.status()["people"]}
    assert people["gran"]["state"] == "online"  # her device is a peer and online (login names ignore case)
    assert people["kid"]["state"] == "joined" and people["kid"]["login"] == "kid@example.com"
    assert people["gran"]["page_url"] == "" and people["gran"]["invite_url"] == ""


def test_the_page_info_only_for_a_live_invite(api):
    fa.save_key(KEY)
    fa.invite("u1", "gran", "Gran")
    token = _token()
    assert fa.page_info("short") is None and fa.page_info("x" * 32) is None
    info = fa.page_info(token)
    assert info == {
        "name": "Gran",
        "accepted": False,
        "invite_url": "https://login.tailscale.com/admin/invite/code100",
        "kiboto_url": "https://attic.example-tailnet.ts.net/",
    }
    data = fa._state()
    data["invites"][token]["expires"] = time.time() - 1
    fa._save(data)
    assert fa.page_info(token) is None
    assert fa.status()["people"][0]["state"] == "expired"


def test_revoking(api):
    fa.save_key(KEY)
    with pytest.raises(KeyError):
        fa.revoke("u1")
    fa.invite("u1", "gran", "Gran")
    assert fa.revoke("u1")["remove_share_at"] == ""
    assert "100" not in api.invites  # an open invite is withdrawn at Tailscale
    fa.invite("u1", "gran", "Gran")
    api.invites["101"].update(accepted=True, acceptedBy={"loginName": "gran@example.com"})
    fa.refresh()
    assert fa.revoke("u1")["remove_share_at"] == fa.MACHINES_PAGE  # an accepted share goes in Tailscale


def test_headscale_and_no_tailscale(api, monkeypatch):
    fa.save_key(KEY)
    monkeypatch.setattr(fa, "_on_headscale", lambda: True)
    with pytest.raises(fa.FamilyAccessError, match="Headscale"):
        fa.invite("u1", "gran", "Gran")
    monkeypatch.setattr(fa, "_on_headscale", lambda: False)
    monkeypatch.setattr(fa, "_tailscale", lambda: {})
    assert fa.status()["tailscale"] is False
    with pytest.raises(fa.FamilyAccessError, match="isn't connected"):
        fa.invite("u1", "gran", "Gran")


def test_the_key_is_resealed(api):
    assert fa.reseal() == 0
    fa.save_key(KEY)
    assert fa.reseal() == 1
    from backend import secret_box

    assert secret_box.unseal(fa._state()["api_key"]) == KEY


def test_the_public_page_and_its_state(client, api):
    fa.save_key(KEY)
    fa.invite("u1", "gran", "Gran")
    token = _token()
    res = client.get(f"/api/fs/shared/join/{token}")
    assert res.status_code == 200
    assert "script-src 'sha256-" in res.headers["content-security-policy"]
    assert res.headers["cache-control"] == "no-store"
    assert "Hi Gran" in res.text and "code100" in res.text and "apps.apple.com" in res.text
    assert client.get(f"/api/fs/shared/join/{token}/state").json() == {"accepted": False}
    api.invites["100"].update(accepted=True, acceptedBy={"loginName": "gran@example.com"})
    assert client.get(f"/api/fs/shared/join/{token}/state").json() == {"accepted": True}
    page = client.get(f"/api/fs/shared/join/{token}").text
    assert 'class="done"' in page and "code100" not in page
    assert client.get("/api/fs/shared/join/" + "y" * 32).status_code == 404
    assert client.get("/api/fs/shared/join/" + "y" * 32 + "/state").status_code == 404


@pytest.mark.real_confirmations
def test_the_owner_routes(client, auth_headers, api):
    me = client.get("/api/users", headers=auth_headers).json()["users"][0]
    assert client.get("/api/network/family-access", headers=auth_headers).json()["has_key"] is False
    assert (
        client.put("/api/network/family-access/key", json={"key": "nope-nope-nope"}, headers=auth_headers).status_code
        == 400
    )
    assert client.put("/api/network/family-access/key", json={"key": KEY}, headers=auth_headers).json()["has_key"]
    res = client.post("/api/network/family-access/invites", json={"user_id": me["id"]}, headers=auth_headers)
    assert res.status_code == 428  # confirmed first
    res = client.post("/api/network/family-access/invites", json={"user_id": "nobody"}, headers=auth_headers)
    assert res.status_code == 404
    assert client.delete(f"/api/network/family-access/invites/{me['id']}", headers=auth_headers).status_code == 404
    assert client.delete("/api/network/family-access/key", headers=auth_headers).json()["has_key"] is False
