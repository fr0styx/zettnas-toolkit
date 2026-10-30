"""NSEC-6: the office suite relays the family's sign-ins; its address isn't blocked for them."""

import ipaddress

from backend.services import ip_block


def test_an_app_on_zettnas_network_isnt_blocked(monkeypatch):
    ip_block._reset_for_tests()
    monkeypatch.setattr(ip_block, "_app_network", lambda: ipaddress.ip_network("172.20.0.0/16"))
    for _ in range(ip_block.FAIL_LIMIT + 5):
        assert ip_block.record_auth_failure("172.20.0.7", "WebDAV") is False
    assert not ip_block.is_blocked("172.20.0.7")
    blocked = [ip_block.record_auth_failure("192.168.1.66", "WebDAV") for _ in range(ip_block.FAIL_LIMIT)]
    assert blocked[-1] is True  # a LAN address is still blocked as before


def test_the_network_comes_from_zettnas_container(monkeypatch):
    from backend.services import docker_client

    monkeypatch.setattr(ip_block, "_app_net", {"at": -1e9, "net": None})
    me = {
        "NetworkSettings": {
            "Networks": {
                "bridge": {"IPAddress": "172.17.0.2", "IPPrefixLen": 16},
                "zettnas_default": {"IPAddress": "172.20.0.3", "IPPrefixLen": 16},
            }
        }
    }
    monkeypatch.setattr(docker_client, "request", lambda m, p, **k: (200, me))
    assert ip_block._app_network() == ipaddress.ip_network("172.20.0.0/16")


def test_host_networking_trusts_nothing(monkeypatch):
    from backend.services import docker_client

    monkeypatch.setattr(ip_block, "_app_net", {"at": -1e9, "net": None})
    monkeypatch.setattr(
        docker_client, "request", lambda m, p, **k: (200, {"NetworkSettings": {"Networks": {"host": {}}}})
    )
    assert ip_block._app_network() is None
    assert ip_block._relay("192.168.1.5") is False
