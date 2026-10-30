"""Each person's clock on their account; a server zone from an administrator's browser."""

import pytest

from backend.services import identity


@pytest.fixture
def ident(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "IDENTITY_FILE", str(tmp_path / "identity.json"))
    monkeypatch.delenv("TZ", raising=False)
    applied = []
    monkeypatch.setattr(identity, "apply_timezone", lambda tz: applied.append(tz) or True)
    return applied


def test_no_zone_takes_the_browser_one(ident):
    assert identity.get_identity()["timezone_source"] == ""
    got = identity.detect_timezone("America/New_York")
    assert got["timezone"] == "America/New_York" and got["timezone_source"] == "browser"
    assert ident == ["America/New_York"]
    # a second browser elsewhere doesn't move it
    assert identity.detect_timezone("Asia/Tokyo")["timezone"] == "America/New_York"
    with pytest.raises(ValueError):
        identity.detect_timezone("Mars/Base")


def test_a_chosen_or_container_zone_stays(ident, monkeypatch):
    identity.set_identity(timezone="Europe/Berlin")
    assert identity.get_identity()["timezone_source"] == "chosen"
    assert identity.detect_timezone("Asia/Tokyo")["timezone"] == "Europe/Berlin"
    identity.set_identity(timezone="")
    monkeypatch.setenv("TZ", "Europe/Paris")
    assert identity.get_identity() == {"server_name": "", "timezone": "Europe/Paris", "timezone_source": "container"}
    assert identity.detect_timezone("Asia/Tokyo")["timezone"] == "Europe/Paris"


def test_the_api(client, auth_headers, ident):
    r = client.post("/api/system/identity/detected-timezone", headers=auth_headers, json={"timezone": "Asia/Tokyo"})
    assert r.status_code == 200 and r.json()["timezone_source"] == "browser"
    bad = client.post("/api/system/identity/detected-timezone", headers=auth_headers, json={"timezone": "Nope/No"})
    assert bad.status_code == 400


def test_the_front_screen_starts_on_the_server_zone(monkeypatch):
    from backend.hardware import storage

    monkeypatch.setattr(storage, "read_json_cached", lambda *a, **k: None)
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert storage.get_current_layout()["timezone"] == "Asia/Tokyo"
    monkeypatch.delenv("TZ")
    assert storage.get_current_layout()["timezone"] == "UTC"


def test_my_clock_preferences_are_checked(monkeypatch):
    from backend.api import auth

    user = {"id": "u1", "username": "mia", "role_id": "kid", "preferences": {"advanced": False}}
    saved = {}
    monkeypatch.setattr(auth, "_get_authenticated_user", lambda request: user)
    monkeypatch.setattr(auth, "_is_person_session", lambda u: True)
    monkeypatch.setattr("backend.users_db.update_user_profile", lambda uid, preferences: saved.update(preferences))

    out = auth.put_my_preferences(auth.MyPreferences(timezone="Asia/Tokyo", clock_format="12"), None)
    assert out["preferences"] == {"advanced": False, "timezone": "Asia/Tokyo", "clock_format": "12"}
    assert auth.put_my_preferences(auth.MyPreferences(timezone="auto"), None)["preferences"]["timezone"] == "auto"
    bad = auth.put_my_preferences(auth.MyPreferences(timezone="Mars/Base"), None)
    assert bad.status_code == 400
    with pytest.raises(ValueError):
        auth.MyPreferences(clock_format="13")
