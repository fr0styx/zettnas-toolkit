"""Decisions B2 and B6 (12 Nov 2026): kids and guests closed once on upgrade; Immich's family
sign-in follows its move to a port of its own."""

import json
import os

import pytest


def test_b2_closes_family_shares_once_and_names_who(tmp_path, monkeypatch):
    from backend import config
    from backend.services import safe_defaults_advisor, security_upgrade

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    closed, events = [], []
    monkeypatch.setattr(safe_defaults_advisor, "family_share_finding", lambda: {"params": {"people": "mia, tom"}})
    monkeypatch.setattr(safe_defaults_advisor, "close_family_shares", lambda: closed.append(1) or "ok")
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append(a))
    assert security_upgrade.run_2_0_2_once() == ["mia", "tom"]
    assert closed == [1] and "mia, tom" in events[0][2]
    with open(os.path.join(tmp_path, security_upgrade.MARKER_2_0_2)) as fh:
        marker = json.load(fh)
    assert marker["people"] == ["mia", "tom"]
    # once: a later choice to open folders to them again is kept
    assert security_upgrade.run_2_0_2_once() == [] and closed == [1]


def test_b2_nothing_to_close_still_marks_done(tmp_path, monkeypatch):
    from backend import config
    from backend.services import safe_defaults_advisor, security_upgrade

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(safe_defaults_advisor, "family_share_finding", lambda: None)
    assert security_upgrade.run_2_0_2_once() == []
    assert os.path.exists(os.path.join(tmp_path, security_upgrade.MARKER_2_0_2))


def test_b2_a_failure_tries_again_at_the_next_start(tmp_path, monkeypatch):
    from backend import config
    from backend.services import safe_defaults_advisor, security_upgrade

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))

    def broken():
        raise OSError("disk")

    monkeypatch.setattr(safe_defaults_advisor, "family_share_finding", broken)
    assert security_upgrade.run_2_0_2_once() == []
    assert not os.path.exists(os.path.join(tmp_path, security_upgrade.MARKER_2_0_2))


def test_the_public_helpers_are_the_check_and_its_fix(monkeypatch):
    from backend.services import safe_defaults_advisor as sda

    monkeypatch.setattr(sda, "_share_access_finding", lambda: {"id": "share_access_family"})
    monkeypatch.setattr(sda, "_fix_share_access_family", lambda: "closed")
    assert sda.family_share_finding()["id"] == "share_access_family" and sda.close_family_shares() == "closed"


@pytest.fixture
def immich_cfg(tmp_path, monkeypatch):
    from backend.services import immich_photos

    store = {}
    monkeypatch.setattr(immich_photos, "_cfg", lambda: dict(store))
    monkeypatch.setattr(immich_photos, "_save", lambda c: store.clear() or store.update(c))
    return store


def test_b6_the_connection_is_remembered(immich_cfg):
    from backend.services import immich_photos

    assert immich_photos.sso_connection() == {}
    immich_photos.set_sso(True, "https://nas.tail.ts.net:2283", "owner@example.com")
    assert immich_photos.sso_connection() == {"url": "https://nas.tail.ts.net:2283", "email": "owner@example.com"}
    immich_photos.set_sso(False)
    assert immich_photos.sso_connection() == {}


def test_b6_follow_move_connects_again_and_lists_the_provider_addresses(immich_cfg, monkeypatch):
    from backend.services import immich_photos, immich_sso

    immich_photos.set_sso(True, "https://nas.ts.net:2283", "owner@example.com")
    events, calls = [], []
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr(immich_sso, "app_dir", lambda: "/tmp/immich")
    monkeypatch.setattr("backend.services.oidc.load_config", lambda: {"issuer": "https://id.example.com"})

    def fake_connect(url, email, app_dir, cfg, *a, **k):
        calls.append((url, email))
        return {
            "ok": True,
            "redirect_uris": ["app.immich:///oauth-callback", f"{url}/auth/login", f"{url}/user-settings"],
        }

    monkeypatch.setattr(immich_sso, "connect", fake_connect)
    res = immich_sso.follow_move("https://nas.ts.net:12283")
    assert res["ok"] is True and calls == [("https://nas.ts.net:12283", "owner@example.com")]
    assert immich_photos.sso_connection()["url"] == "https://nas.ts.net:12283"
    assert events[0][0] == "info" and "https://nas.ts.net:12283/auth/login" in events[0][2]
    assert "app.immich" not in events[0][2]  # only web addresses go to the provider


def test_b6_a_failed_reconnect_says_to_connect_again(immich_cfg, monkeypatch):
    from backend.services import immich_photos, immich_sso

    immich_photos.set_sso(True, "https://nas.ts.net:2283", "owner@example.com")
    events = []
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr(immich_sso, "app_dir", lambda: "/tmp/immich")
    monkeypatch.setattr("backend.services.oidc.load_config", lambda: {"issuer": "https://id.example.com"})

    def refuses(*a, **k):
        raise immich_sso.ImmichSsoError("Immich is not reachable")

    monkeypatch.setattr(immich_sso, "connect", refuses)
    res = immich_sso.follow_move("https://nas.ts.net:12283")
    assert res["ok"] is False and events[0][0] == "warning" and "connect Immich again in People" in events[0][2]


def test_b6_nothing_to_follow_without_family_sign_in(immich_cfg):
    from backend.services import immich_sso

    assert immich_sso.follow_move("https://nas.ts.net:12283") == {"skipped": True}


def test_b6_the_move_triggers_the_follow(monkeypatch, tmp_path):
    from backend.services import immich_sso, public_links, remote_access

    followed = []
    monkeypatch.setattr(public_links, "STATE_FILE", str(tmp_path / "pl.json"))
    monkeypatch.setattr(public_links, "_dns_name", lambda: "nas.ts.net")
    monkeypatch.setattr(public_links, "funnel_readiness", lambda: {"ready": True})
    monkeypatch.setattr(public_links, "_port_state", lambda dns: ({}, False, True))
    monkeypatch.setattr(public_links, "immich_to_move", lambda dns=None: "nas.ts.net:12283")
    monkeypatch.setattr(public_links, "_ts", lambda *a, **k: (0, ""))
    monkeypatch.setattr(public_links, "status", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(remote_access, "move_immich", lambda: 12283)
    monkeypatch.setattr(immich_sso, "follow_move", lambda url: followed.append(url) or {"ok": True})
    public_links.enable(8082, move_immich=True)
    assert followed == ["https://nas.ts.net:12283"]


def test_b6_app_dir_falls_back_without_the_container(monkeypatch):
    from backend.services import immich_sso

    monkeypatch.setattr("backend.services.container_mutator._docker_request", lambda *a, **k: (404, {}))
    assert immich_sso.app_dir() == "/mnt/user/appdata/immich"
    monkeypatch.setattr(
        "backend.services.container_mutator._docker_request",
        lambda *a, **k: (200, {"Mounts": [{"Destination": "/data", "Source": "/mnt/user/appdata/immich2/library"}]}),
    )
    assert immich_sso.app_dir() == "/mnt/user/appdata/immich2"
