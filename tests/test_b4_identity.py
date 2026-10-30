"""UX-17: the server's name and time zone from the setup wizard."""

import os
import time

import pytest


@pytest.fixture
def keep_tz():
    before = os.environ.get("TZ")
    yield
    if before is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = before
    time.tzset()


def test_name_and_time_zone_are_saved_and_applied(client, auth_headers, keep_tz):
    r = client.put(
        "/api/system/identity", json={"server_name": "Home server", "timezone": "Europe/Berlin"}, headers=auth_headers
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"server_name": "Home server", "timezone": "Europe/Berlin", "timezone_source": "chosen"}
    assert os.environ["TZ"] == "Europe/Berlin" and time.strftime("%Z") in ("CET", "CEST")
    assert client.get("/api/system/identity", headers=auth_headers).json()["server_name"] == "Home server"
    # a value left out stays as it was
    r = client.put("/api/system/identity", json={"server_name": "Attic"}, headers=auth_headers)
    assert r.json() == {"server_name": "Attic", "timezone": "Europe/Berlin", "timezone_source": "chosen"}


@pytest.mark.parametrize("body", [{"timezone": "Mars/Olympus"}, {"server_name": "<script>"}, {"server_name": "x" * 41}])
def test_bad_values_are_refused(client, auth_headers, body, keep_tz):
    r = client.put("/api/system/identity", json=body, headers=auth_headers)
    assert r.status_code in (400, 422)


def test_the_saved_time_zone_wins_at_startup(tmp_path, monkeypatch, keep_tz):
    from backend.services import identity

    monkeypatch.setattr(identity, "IDENTITY_FILE", str(tmp_path / "identity.json"))
    identity.apply_saved_timezone()  # nothing saved: nothing changes
    (tmp_path / "identity.json").write_text('{"timezone": "Asia/Tokyo"}')
    identity.apply_saved_timezone()
    assert os.environ["TZ"] == "Asia/Tokyo"
    (tmp_path / "identity.json").write_text('{"timezone": "Nowhere/Land"}')
    identity.apply_saved_timezone()  # unknown here: kept as it was, with a warning
    assert os.environ["TZ"] == "Asia/Tokyo"
    (tmp_path / "identity.json").write_text("[]")
    assert identity.get_identity()["server_name"] == ""


def test_without_a_time_zone_database_only_utc_is_known(monkeypatch):
    import builtins

    from backend.services import identity

    identity._zones.cache_clear()
    real_import = builtins.__import__

    def no_zoneinfo(name, *a, **k):
        if name == "zoneinfo":
            raise ImportError
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_zoneinfo)
    try:
        assert identity._zones() == frozenset({"UTC"})
    finally:
        identity._zones.cache_clear()
