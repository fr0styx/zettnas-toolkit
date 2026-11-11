"""SET-14: Apprise addresses send only while the channel is on; addresses saved before the switch stay on."""

from backend.services.notifications import build_apprise_urls

URL = "gotify://gotify.example/token"


def test_on_by_default():
    assert URL in build_apprise_urls({"apprise_urls": [URL]})


def test_off_sends_nothing_from_apprise():
    assert URL not in build_apprise_urls({"apprise_urls": [URL], "apprise_enabled": False})


def test_the_switch_is_saved(client, auth_headers):
    res = client.post(
        "/api/notifications/config", json={"apprise_urls": [URL], "apprise_enabled": False}, headers=auth_headers
    )
    assert res.status_code in (200, 201), res.text
    cfg = client.get("/api/notifications/config", headers=auth_headers).json()
    assert cfg.get("apprise_enabled") is False
