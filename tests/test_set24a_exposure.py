"""SET-24: one answer for what reaches this NAS from outside, read from the live settings."""

import pytest

from backend.services import exposure, netbird, public_apps, public_links, remote_access, tailnet_ports

LINKS = {"port": 8443, "owner": "share_links", "paths": ["/api/fs/shared"], "targets": []}
APP = {"port": 10000, "owner": "public_app", "paths": ["/"], "targets": []}
OWN = {"port": 443, "owner": "kiboto", "paths": ["/"], "targets": []}


def test_nothing_on_is_off():
    x = exposure.judge("Stopped", False, [], False, set(), None)
    assert (x["level"], x["tone"], x["via"]) == ("off", "neutral", [])


def test_tailscale_or_netbird_alone_is_private():
    assert exposure.judge("Running", False, [], False, set(), 80)["via"] == ["tailscale"]
    x = exposure.judge("NotInstalled", True, [], False, set(), None)
    assert (x["level"], x["via"]) == ("private", ["netbird"])


def test_what_kiboto_turned_on_is_public_and_neutral():
    x = exposure.judge("Running", False, [LINKS, APP], True, {10000}, 90)
    assert (x["level"], x["tone"], x["share_links"], x["apps"], x["unexpected"]) == ("public", "neutral", True, 1, [])


def test_public_against_the_record_is_red():
    x = exposure.judge("Running", False, [LINKS, OWN], False, set(), 90)
    assert (x["tone"], x["reason"], x["unexpected"]) == ("red", "unexpected_public", [443, 8443])


@pytest.mark.parametrize(
    ("state", "days", "reason"),
    [("NeedsLogin", None, "sign_in"), ("Running", 14, "key_expiring"), ("Running", 15, ""), ("Running", None, "")],
)
def test_amber_for_a_sign_in_or_a_key_running_out(state, days, reason):
    x = exposure.judge(state, False, [], False, set(), days)
    assert x["reason"] == reason
    assert x["tone"] == ("amber" if reason else "neutral")


def test_summary_reads_the_live_state(monkeypatch):
    monkeypatch.setattr(remote_access, "status", lambda: {"state": "Running"})
    monkeypatch.setattr(tailnet_ports, "public_now", lambda: [LINKS])
    monkeypatch.setattr(public_links, "recorded_on", lambda: True)
    monkeypatch.setattr(public_apps, "recorded_ports", lambda: set())
    monkeypatch.setattr(netbird, "status", lambda: {"state": "NotInstalled"})
    monkeypatch.setattr(exposure, "_key_days", lambda: 40)
    x = exposure.summary()
    assert (x["level"], x["checked"], x["key_days"]) == ("public", True, 40)
    monkeypatch.setattr(tailnet_ports, "public_now", lambda: None)
    assert exposure.summary()["checked"] is False


def test_summary_without_tailscale_asks_nothing_public(monkeypatch):
    asked = []
    monkeypatch.setattr(remote_access, "status", lambda: {"state": "NotInstalled"})
    monkeypatch.setattr(tailnet_ports, "public_now", lambda: asked.append(1))
    monkeypatch.setattr(public_links, "recorded_on", lambda: False)
    monkeypatch.setattr(public_apps, "recorded_ports", lambda: set())

    def broken():
        raise netbird.NetbirdError("no docker")

    monkeypatch.setattr(netbird, "status", broken)
    x = exposure.summary()
    assert (x["level"], x["checked"], asked) == ("off", True, [])


def test_key_days_come_from_the_cached_status(monkeypatch):
    from backend.hardware.net import mesh

    monkeypatch.setattr(mesh, "cached_mesh_vpn_status", lambda: {"tailscale": {"key_expiry_days": 9}})
    assert exposure._key_days() == 9
    monkeypatch.setattr(mesh, "cached_mesh_vpn_status", lambda: {"tailscale": {}})
    assert exposure._key_days() is None


def test_records(monkeypatch, tmp_path):
    monkeypatch.setattr(public_links, "_state", lambda: {"enabled": True})
    assert public_links.recorded_on() is True
    monkeypatch.setattr(public_apps, "_state", lambda: {"10000": {"name": "jellyfin"}, "x": {}})
    assert public_apps.recorded_ports() == {10000}


def test_the_route(client, auth_headers, monkeypatch):
    monkeypatch.setattr(exposure, "summary", lambda: {"level": "off", "tone": "neutral"})
    r = client.get("/api/network/exposure", headers=auth_headers)
    assert r.status_code == 200 and r.json()["level"] == "off"
