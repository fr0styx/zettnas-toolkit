"""NFEAT-2 / D13: share links from anywhere through Tailscale Funnel, only the share-link path."""

import json

import pytest

from backend.services import public_links as pl

DNS = "family-nas.tail1234.ts.net"


class FakeTailscale:
    def __init__(self, connected=True, needs_approval=False, fails=False):
        self.connected, self.needs_approval, self.fails = connected, needs_approval, fails
        self.funnel = {}
        self.calls = []

    def __call__(self, args, timeout=8.0):
        self.calls.append(args)
        if args[:2] == ["status", "--json"]:
            return (
                (
                    0,
                    json.dumps(
                        {
                            "Self": {
                                "DNSName": DNS + ".",
                                "ID": "nTestNode1CNTRL",
                                "CapMap": {
                                    "funnel": None,
                                    "https://tailscale.com/cap/funnel-ports?ports=443,8443,10000": None,
                                },
                            },
                            "CertDomains": [DNS],
                        }
                    ),
                )
                if self.connected
                else (1, "not running")
            )
        if args[:3] == ["funnel", "status", "--json"]:
            return 0, json.dumps(self.funnel)
        if args[0] == "funnel" and args[-1] == "off":
            self.funnel = {}
            return 0, ""
        if args[0] == "funnel":
            if self.fails:
                return 1, "error: serve config denied"
            if self.needs_approval:
                return (
                    1,
                    "Funnel is not enabled on your tailnet.\nTo enable, visit:\n\n    https://login.tailscale.com/f/funnel?node=abc\n",
                )
            host = f"{DNS}:{pl.FUNNEL_PORT}"
            path = args[4].split("=", 1)[1]
            self.funnel = {"Web": {host: {"Handlers": {path: {"Proxy": args[5]}}}}, "AllowFunnel": {host: True}}
            return 0, ""
        return 1, "unexpected"


@pytest.fixture
def ts(monkeypatch, tmp_path):
    monkeypatch.setattr(pl, "STATE_FILE", str(tmp_path / "public_links.json"))
    fake = FakeTailscale()
    monkeypatch.setattr(pl, "_ts", fake)
    return fake


def test_only_the_share_link_path_is_published_on_its_own_port(ts):
    assert pl.status()["enabled"] is False and pl.public_url("abc") == ""
    st = pl.enable(8082)
    funnel = next(c for c in ts.calls if c[0] == "funnel" and "--bg" in c)
    assert funnel == [
        "funnel",
        "--bg",
        "--yes",
        "--https=8443",
        "--set-path=/api/fs/shared",
        "http://127.0.0.1:8082/api/fs/shared",
    ]
    assert st.pop("funnel")["ready"] is True and st.pop("pending") is False
    assert st == {
        "enabled": True,
        "live": True,
        "port_public": True,
        "also_public": [],
        "tailscale": True,
        "base_url": f"https://{DNS}:8443",
        "approval_url": "",
        "error": "",
    }
    assert pl.public_url("abc") == f"https://{DNS}:8443/api/fs/shared/abc"


def test_the_first_time_tailscale_may_ask_for_approval(ts):
    ts.needs_approval = True
    st = pl.enable(8082)
    assert st["approval_url"] == "https://login.tailscale.com/f/funnel?node=abc" and not st["live"] and not st["error"]
    assert pl.public_url("abc") == ""  # not yet
    ts.needs_approval = False
    st = pl.enable(8082)  # after the approval
    assert st["live"] and st["approval_url"] == "" and pl.public_url("x").endswith("/api/fs/shared/x")


def test_off_and_without_tailscale(ts):
    pl.enable(8082)
    st = pl.disable()
    assert st["enabled"] is False and ts.funnel == {} and pl.public_url("abc") == ""
    assert ["funnel", "--https=8443", "--set-path=/api/fs/shared", "off"] in ts.calls
    ts.connected = False
    st = pl.enable(8082)
    assert not st["enabled"] and "Tailscale isn't connected" in st["error"] and not st["tailscale"]


def test_a_refusal_is_said(ts):
    ts.fails = True
    st = pl.enable(8082)
    assert not st["enabled"] and "denied" in st["error"]


def test_live_needs_both_the_path_and_funnel_allowed(ts):
    host = f"{DNS}:8443"
    ts.funnel = {"Web": {host: {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8082"}}}}, "AllowFunnel": {host: True}}
    assert pl.live(DNS) is False  # the whole interface is not what this feature publishes
    ts.funnel = {"Web": {host: {"Handlers": {"/api/fs/shared/": {}}}}, "AllowFunnel": {}}
    assert pl.live(DNS) is False
    ts.funnel = "not json"
    assert pl.live(DNS) is False


def test_the_api_and_share_links_get_the_address(client, auth_headers, ts, tmp_path, monkeypatch):
    from backend.api import fs as fs_api

    r = client.get("/api/network/public-links", headers=auth_headers)
    assert r.status_code == 200 and r.json()["enabled"] is False
    r = client.put("/api/network/public-links", json={"enabled": True}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["live"] is True
    pool = tmp_path / "pool"
    pool.mkdir()
    (pool / "a.txt").write_text("hi")
    for mod in (fs_api, fs_api.common, fs_api.share_links):
        monkeypatch.setattr(mod, "ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(fs_api.share_links, "SHARE_LINKS_FILE", str(tmp_path / "links.json"))
    made = client.post("/api/fs/share-links", json={"path": str(pool / "a.txt")}, headers=auth_headers)
    assert made.status_code == 200, made.text
    assert made.json()["public_url"] == f"https://{DNS}:8443/api/fs/shared/{made.json()['token']}"
    listed = client.get("/api/fs/share-links", headers=auth_headers).json()
    assert listed[0]["public_url"].startswith(f"https://{DNS}:8443/")
    assert (
        client.put("/api/network/public-links", json={"enabled": False}, headers=auth_headers).json()["enabled"]
        is False
    )


@pytest.mark.real_confirmations
def test_turning_it_on_asks_first(client, auth_headers, ts):
    r = client.put("/api/network/public-links", json={"enabled": True}, headers=auth_headers)
    assert r.status_code == 428 and r.json()["action"] == "network.public_links"
    assert not any(c[0] == "funnel" and "--bg" in c for c in ts.calls)
