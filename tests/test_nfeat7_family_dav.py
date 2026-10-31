"""NFEAT-7: the office suite carries a family calendar and address book."""

import pytest

from backend.services import family_dav
from backend.services.catalog_templates import CURATED_APP_CATALOG


def test_new_installs_add_calendar_and_contacts():
    office = next(a for a in CURATED_APP_CATALOG if a["id"] == "office-suite")
    labels = [s["label"] for s in office["after_start"]]
    assert labels[-2:] == ["Adding the family calendar", "Adding the family address book"]
    assert office["after_start"][-2:] == family_dav.STEPS


def _containers(monkeypatch, found, status=200):
    monkeypatch.setattr("backend.services.docker_client.request", lambda *a, **k: (status, found))


def test_the_office_suite_is_found(monkeypatch):
    _containers(
        monkeypatch,
        [
            {"Image": "lscr.io/linuxserver/jellyfin", "Names": ["/jellyfin"], "State": "running"},
            {
                "Image": "nextcloud:apache",
                "Names": ["/office-suite"],
                "State": "running",
                "Ports": [{"PrivatePort": 80, "PublicPort": 8093}],
            },
        ],
    )
    assert family_dav.office_container() == {"name": "office-suite", "running": True, "port": 8093}
    assert family_dav.status("nas.local") == {
        "installed": True,
        "running": True,
        "server": "nas.local:8093",
        "caldav": "http://nas.local:8093/remote.php/dav",
        "carddav": "http://nas.local:8093/remote.php/dav",
    }
    assert family_dav.status("bad host!")["server"] == "localhost:8093"
    _containers(monkeypatch, [])
    assert family_dav.status("nas") == {"installed": False}
    _containers(monkeypatch, {"message": "x"}, status=500)
    assert family_dav.office_container() is None

    def down(*a, **k):
        raise OSError("no socket")

    monkeypatch.setattr("backend.services.docker_client.request", down)
    assert family_dav.office_container() is None


def test_adding_them_to_an_older_install(monkeypatch):
    monkeypatch.setattr(family_dav, "office_container", lambda: {"name": "office-suite", "running": True, "port": 8093})
    ran = []
    answers = iter([(0, ""), (1, "boom")])

    def exec_in(container, cmd, user="", timeout=300):
        ran.append((container, cmd[-1], user))
        return next(answers)

    monkeypatch.setattr("backend.services.app_after_start.exec_in", exec_in)
    assert family_dav.add_apps() == {
        "added": ["Adding the family calendar"],
        "failed": ["Adding the family address book"],
    }
    assert ran[0][0] == "office-suite" and "app:install calendar" in ran[0][1] and ran[0][2] == "www-data"
    monkeypatch.setattr(
        family_dav, "office_container", lambda: {"name": "office-suite", "running": False, "port": 8093}
    )
    with pytest.raises(ValueError, match="Start the office suite"):
        family_dav.add_apps()


def test_the_api(client, auth_headers, monkeypatch):
    monkeypatch.setattr(family_dav, "status", lambda host: {"installed": False, "host": host})
    assert client.get("/api/docker/catalog/office-suite/family", headers=auth_headers).json()["installed"] is False

    def refuse():
        raise ValueError("Start the office suite first, then add the calendar and contacts.")

    monkeypatch.setattr(family_dav, "add_apps", refuse)
    r = client.post("/api/docker/catalog/office-suite/family", headers=auth_headers)
    assert r.status_code == 409 and "Start the office suite" in r.json()["detail"]
