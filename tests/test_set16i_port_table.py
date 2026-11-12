"""SET-16 stage 3: one table says which feature owns which Tailscale port, and one function lists
what Funnel puts on the internet."""

import json

import pytest

from backend.services import family_signin, public_apps, public_links, remote_access, tailnet_ports

DNS = "kiboto.tail1.ts.net"


def test_the_features_take_their_ports_from_the_table():
    assert public_links.FUNNEL_PORT == tailnet_ports.SHARE_LINKS == 8443
    assert public_links.PATH == tailnet_ports.SHARE_PATH
    assert public_apps.APP_PORTS == (10000, 443)
    assert remote_access.IMMICH_HTTPS_PORT == tailnet_ports.IMMICH_BEFORE_MOVE
    assert remote_access.APP_HTTPS_OFFSET == tailnet_ports.APP_OFFSET
    assert family_signin.HTTPS_PORT == family_signin.PORT + tailnet_ports.APP_OFFSET
    assert set(tailnet_ports.PUBLIC_APP_PORTS) <= set(tailnet_ports.FUNNEL_ALLOWS)
    assert tailnet_ports.SHARE_LINKS in tailnet_ports.FUNNEL_ALLOWS


@pytest.mark.parametrize(
    ("port", "who"),
    [(443, "kiboto"), (8443, "share_links"), (10000, "public_app"), (18096, "app"), (8080, "other")],
)
def test_every_port_has_one_owner(port, who):
    assert tailnet_ports.owner(port) == who


@pytest.mark.parametrize("out", ["", "not json", "[1, 2]", None])
def test_an_unreadable_status_is_none(out):
    assert tailnet_ports.parse_funnel_status(out) is None


def test_null_is_an_empty_status():
    assert tailnet_ports.parse_funnel_status("null") == {}


DOC = {
    "AllowFunnel": {f"{DNS}:8443": True, f"{DNS}:443": False, f"{DNS}:10000": True, "odd": True},
    "Web": {
        f"{DNS}:8443": {
            "Handlers": {
                "/api/fs/shared": {"Proxy": "http://127.0.0.1:8082/api/fs/shared"},
                "/": {"Proxy": "http://127.0.0.1:2283"},
            }
        },
        f"{DNS}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8082"}}},
        f"{DNS}:10000": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8096"}, "/x": None}},
    },
}


def test_published_lists_each_public_port_with_what_it_serves():
    assert tailnet_ports.published(DOC) == [
        {
            "port": 8443,
            "owner": "share_links",
            "paths": ["/", "/api/fs/shared"],
            "targets": ["http://127.0.0.1:2283", "http://127.0.0.1:8082/api/fs/shared"],
        },
        {"port": 10000, "owner": "public_app", "paths": ["/", "/x"], "targets": ["http://127.0.0.1:8096"]},
    ]
    assert tailnet_ports.published({}) == []


def test_public_now_reads_tailscale_once(monkeypatch):
    from backend.hardware.net import tailscale

    calls = []

    def fake(args, timeout=10.0):
        calls.append(args)
        return 0, json.dumps(DOC)

    monkeypatch.setattr(tailscale, "run_tailscale_cmd", fake)
    rows = tailnet_ports.public_now()
    assert [r["port"] for r in rows] == [8443, 10000]
    assert calls == [["funnel", "status", "--json"]]
    monkeypatch.setattr(tailscale, "run_tailscale_cmd", lambda args, timeout=10.0: (1, "no tailscale"))
    assert tailnet_ports.public_now() is None  # can't ask is not "nothing public"
    monkeypatch.setattr(tailscale, "run_tailscale_cmd", lambda args, timeout=10.0: (0, "garbage"))
    assert tailnet_ports.public_now() is None


def test_remote_access_public_ports_use_the_shared_reader(monkeypatch):
    monkeypatch.setattr(remote_access, "_json", lambda args: (0, DOC))
    assert remote_access._public_ports() == {8443, 10000}
