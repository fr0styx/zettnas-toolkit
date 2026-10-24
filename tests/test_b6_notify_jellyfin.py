"""Batch 6: notification digests, per-person alerts, one-step Jellyfin."""

import os
import time
from types import SimpleNamespace

import pytest

from backend.services import app_catalog
from backend.services import notifications as nt


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NOTIFICATIONS_FILE", str(tmp_path / "n.json"))
    monkeypatch.setattr(nt, "DIGEST_FILE", str(tmp_path / "digest.json"))
    monkeypatch.setattr(nt, "ROUTES_FILE", str(tmp_path / "routes.json"))
    nt._alert_history.clear()
    sent = []
    monkeypatch.setattr(nt, "_dispatch_ntfy", lambda c, t, m, lv: sent.append(("ntfy", c.get("ntfy_topic"), t)) or True)
    monkeypatch.setattr(
        nt, "_dispatch_apprise", lambda c, t, m, lv: sent.append(("mail", c.get("email_to"), t)) or True
    )
    monkeypatch.setattr(nt, "_find_unraid_notify", lambda: None)
    base = dict(nt.DEFAULT_NOTIFICATION_CONFIG)
    base.update(
        {"enabled": True, "ntfy_enabled": True, "ntfy_topic": "house", "unraid_notify": False, "push_enabled": False}
    )
    nt.save_notification_config(base)
    return sent


def test_digest_holds_non_urgent_alerts_until_the_hour(cfg):
    c = nt.load_notification_config()
    c.update({"digest_mode": "daily", "digest_hour": time.localtime().tm_hour})
    nt.save_notification_config(c)
    assert nt.send_notification("Backup finished", "ok", level="normal", event_type="backup")["reason"] == "digest"
    assert nt.send_notification("Disk 3 is failing", "now", level="critical", event_type="smart")["dispatched"]
    assert [s[2] for s in cfg] == ["Disk 3 is failing"]
    res = nt.send_digest_if_due()
    assert res["sent"] and res["count"] == 1
    assert "daily summary" in cfg[-1][2]
    assert nt.send_digest_if_due()["sent"] is False  # once a day


def test_people_get_the_kinds_they_asked_for(cfg):
    nt.set_route("dad", ntfy_topic="dad-phone", events=["ups", "backup"], min_level="warning")
    nt.set_route("mum", email="mum@example.com", events=["security"], min_level="critical")
    nt.send_notification("Power cut", "on battery", level="warning", event_type="ups")
    nt.send_notification("Possible ransomware", "frozen", level="critical", event_type="security")
    personal = [s for s in cfg if s[1] in ("dad-phone", "mum@example.com")]
    assert ("ntfy", "dad-phone", "Power cut") in personal
    assert not any(s[1] == "dad-phone" and s[2] == "Possible ransomware" for s in personal)
    # mum asked for security mail, but there is no SMTP server configured
    assert not any(s[1] == "mum@example.com" for s in personal)


def test_routes_are_validated(cfg):
    with pytest.raises(ValueError):
        nt.set_route("dad", ntfy_topic="bad topic!")
    with pytest.raises(ValueError):
        nt.set_route("dad", email="not-an-address")
    assert nt.set_route("dad", events=["ups", "made-up"])["events"] == ["ups"]


def test_jellyfin_turns_on_hardware_transcoding(monkeypatch, tmp_path):
    app = app_catalog.get_catalog_app("jellyfin")
    monkeypatch.setattr(app_catalog, "_render_nodes", lambda: [])
    assert app_catalog.hw_transcoding_seed(app) == {}
    monkeypatch.setattr(app_catalog, "_render_nodes", lambda: ["/dev/dri/renderD128"])
    seed = app_catalog.hw_transcoding_seed(app)
    assert "<HardwareAccelerationType>vaapi</HardwareAccelerationType>" in seed["config"]["encoding.xml"]
    assert "/dev/dri/renderD128" in seed["config"]["encoding.xml"]
    app_catalog._write_seed_files(app, str(tmp_path))
    assert os.path.exists(tmp_path / "config" / "encoding.xml")


def test_jellyfin_uses_the_media_share_read_only(monkeypatch, tmp_path):
    media = tmp_path / "Media"
    media.mkdir()
    pal = SimpleNamespace(
        list_shares=lambda: [
            SimpleNamespace(name="documents", mountpoint=str(tmp_path)),
            SimpleNamespace(name="Media", mountpoint=str(media)),
        ]
    )
    monkeypatch.setattr("backend.hardware.pal_storage.get_storage_platform", lambda: pal)
    assert app_catalog.media_library_bind(app_catalog.get_catalog_app("jellyfin")) == f"{media}:/media:ro"
    assert app_catalog.media_library_bind(app_catalog.get_catalog_app("plex")) is None
