"""RES-6: chosen apps on the internet through Tailscale Funnel, never Kiboto's own page."""

import json

import pytest

from backend import legacy_names
from backend.services import public_apps as pa
from backend.services import public_links

DNS = "attic.example-tailnet.ts.net"
CONTAINERS = [
    {
        "Names": [f"/{legacy_names.OLD_APP_CONTAINER}"],
        "Image": f"ghcr.io/{legacy_names.OLD_IMAGE_REPO}:latest",
        "Ports": [{"Type": "tcp", "PublicPort": 8082, "IP": "0.0.0.0"}],
    },
    {"Names": ["/kiboto-sftp"], "Image": "atmoz/sftp", "Ports": [{"Type": "tcp", "PublicPort": 2222, "IP": "0.0.0.0"}]},
    {
        "Names": ["/immich_server"],
        "Image": "ghcr.io/immich-app/immich-server",
        "Ports": [{"Type": "tcp", "PublicPort": 2283, "IP": "0.0.0.0"}, {"Type": "tcp", "PrivatePort": 3001}],
    },
    {"Names": ["/dozzle"], "Image": "amir20/dozzle", "Ports": [{"Type": "tcp", "PublicPort": 9999, "IP": "::"}]},
    {"Names": ["/local-only"], "Image": "x/y", "Ports": [{"Type": "tcp", "PublicPort": 7000, "IP": "127.0.0.1"}]},
    {"Names": ["/same-port"], "Image": "x/z", "Ports": [{"Type": "tcp", "PublicPort": 8082, "IP": "0.0.0.0"}]},
    {"Names": ["/dns"], "Image": "pihole", "Ports": [{"Type": "udp", "PublicPort": 53, "IP": "0.0.0.0"}]},
]


@pytest.fixture
def ts(tmp_path, monkeypatch):
    """A fake Tailscale whose serve config remote access already uses on 443 and 8443."""
    calls = []
    web = {
        f"{DNS}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8082"}}},
        f"{DNS}:8443": {"Handlers": {"/": {}}},
    }
    allow = {}

    def fake(args, timeout=8.0):
        calls.append(args)
        if args[:2] == ["status", "--json"]:
            return 0, json.dumps(
                {
                    "Self": {
                        "DNSName": DNS + ".",
                        "ID": "nTestNode1CNTRL",
                        "CapMap": {"funnel": None, "https://tailscale.com/cap/funnel-ports?ports=443,8443,10000": None},
                    },
                    "CertDomains": [DNS],
                }
            )
        if args[:3] == ["funnel", "status", "--json"]:
            return 0, json.dumps({"Web": web, "AllowFunnel": allow})
        if args[0] == "funnel" and args[-1].startswith("http://"):
            host = f"{DNS}:{args[3].split('=')[1]}"
            web[host] = {"Handlers": {"/": {"Proxy": args[-1]}}}
            allow[host] = True
            return 0, ""
        if args[0] == "funnel" and args[-1] == "off":
            host = f"{DNS}:{args[1].split('=')[1]}"
            web.pop(host, None)
            allow.pop(host, None)
            return 0, ""
        return 1, "unexpected"

    monkeypatch.setattr(public_links, "_ts", fake)
    monkeypatch.setattr(pa, "_docker", lambda path: CONTAINERS)
    monkeypatch.setattr(pa, "_own_port", lambda: 8082)
    monkeypatch.setattr(pa, "STATE_FILE", str(tmp_path / "public_apps.json"))
    monkeypatch.setattr(pa, "_audit", lambda *a: calls.append(["audit", *a]))
    return calls


def test_only_other_apps_with_a_public_tcp_port_are_offered(ts):
    names = {a["name"]: a for a in pa.apps()}
    assert set(names) == {"immich_server", "dozzle"}  # never Kiboto, its sidecars or Kiboto's port
    assert names["immich_server"]["ports"] == [2283]
    assert names["dozzle"]["controls_server"] and not names["immich_server"]["controls_server"]


def test_ports_remote_access_serves_are_not_offered(ts):
    st = pa.status()
    assert st["tailscale"] and st["free_ports"] == [10000]  # 443 serves Kiboto on the tailnet
    with pytest.raises(pa.PublishError, match="already serves"):
        pa.publish("immich_server", 2283, 443)


def test_publish_and_take_off(ts):
    st = pa.publish("immich_server", 2283, 10000, actor="ann")
    assert ["funnel", "--bg", "--yes", "--https=10000", "http://127.0.0.1:2283"] in ts
    [p] = st["published"]
    assert p["name"] == "immich_server" and p["url"] == f"https://{DNS}:10000" and p["live"]
    assert st["free_ports"] == []
    assert any(c[0] == "audit" and c[1] == "public_app.publish" for c in ts)
    with pytest.raises(pa.PublishError, match="already serves immich_server"):
        pa.publish("dozzle", 9999, 10000)
    st = pa.unpublish(10000, actor="ann")
    assert ["funnel", "--https=10000", "off"] in ts
    assert st["published"] == [] and st["free_ports"] == [10000]
    with pytest.raises(KeyError):
        pa.unpublish(10000)


@pytest.mark.parametrize(
    "name,port,funnel,words",
    [
        ("immich_server", 2283, 8443, "Apps go on port"),
        (legacy_names.OLD_APP_CONTAINER, 8082, 10000, "Kiboto's own page"),
        ("same-port", 8082, 10000, "Kiboto's own page"),
        ("local-only", 7000, 10000, "not a running app"),
        ("immich_server", 3001, 10000, "does not publish port 3001"),
        ("bad name!", 1, 10000, "Pick an app"),
    ],
)
def test_what_is_refused(ts, name, port, funnel, words):
    with pytest.raises(pa.PublishError, match=words):
        pa.publish(name, port, funnel)


def test_an_approval_link_is_kept_and_a_refusal_said(ts, monkeypatch):
    real = public_links._ts

    def approval(args, timeout=8.0):
        if args[0] == "funnel" and args[-1].startswith("http://"):
            return 1, "Funnel is not enabled on your tailnet. https://login.tailscale.com/f/funnel?node=abc"
        return real(args, timeout)

    monkeypatch.setattr(public_links, "_ts", approval)
    st = pa.publish("immich_server", 2283, 10000)
    assert st["published"][0]["approval_url"].startswith("https://login.tailscale.com/f/funnel")
    pa.unpublish(10000)
    monkeypatch.setattr(
        public_links,
        "_ts",
        lambda args, timeout=8.0: (
            (1, "boom") if args[0] == "funnel" and args[-1].startswith("http") else real(args, timeout)
        ),
    )
    with pytest.raises(pa.PublishError, match="boom"):
        pa.publish("immich_server", 2283, 10000)


def test_without_tailscale_nothing_is_offered(ts, monkeypatch):
    monkeypatch.setattr(public_links, "_ts", lambda args, timeout=8.0: (1, "Tailscale container is stopped"))
    st = pa.status()
    assert {k: st[k] for k in ("tailscale", "published", "free_ports", "apps", "pending")} == {
        "tailscale": False,
        "published": [],
        "free_ports": [10000, 443],
        "apps": [],
        "pending": None,
    }
    assert st["funnel"]["ready"] is False
    with pytest.raises(pa.PublishError, match="isn't connected"):
        pa.publish("immich_server", 2283, 10000)


@pytest.mark.real_confirmations
def test_the_routes_confirm_first(client, auth_headers, ts):
    res = client.post(
        "/api/network/public-apps",
        json={"name": "immich_server", "host_port": 2283, "funnel_port": 10000},
        headers=auth_headers,
    )
    assert res.status_code == 428
    assert client.get("/api/network/public-apps", headers=auth_headers).json()["free_ports"] == [10000]
    assert client.delete("/api/network/public-apps/10000", headers=auth_headers).status_code == 404
