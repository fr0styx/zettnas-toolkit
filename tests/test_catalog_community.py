"""Catalog growth: community Portainer-format catalogs are offered (off) and labelled community."""

import json

from backend.services import app_catalog


def test_community_source_is_offered_and_syncs_hundreds(tmp_path, monkeypatch):
    monkeypatch.setattr(app_catalog, "CATALOG_SOURCES_FILE", str(tmp_path / "sources.json"))
    monkeypatch.setattr(app_catalog, "CATALOG_CACHE_DIR", str(tmp_path / "cache"))
    sources = app_catalog.get_catalog_sources()
    comm = next(s for s in sources if s["id"] == "community_portainer")
    assert comm["enabled"] is False
    templates = {
        "version": "2",
        "templates": [
            {
                "type": 1,
                "title": f"App {i}",
                "name": f"app{i}",
                "image": f"example/app{i}:latest",
                "categories": ["Media"],
                "ports": [f"{8000 + i}:80/tcp"],
                "env": [{"name": "TZ", "default": "UTC"}],
            }
            for i in range(150)
        ],
    }
    monkeypatch.setattr(
        "backend.services.safe_fetch.safe_fetch", lambda url, **k: (200, {}, json.dumps(templates).encode())
    )
    res = app_catalog.sync_catalog_source("community_portainer")
    assert res["status"] == "ok" and res["item_count"] == 150
    app_catalog.toggle_catalog_source("community_portainer", True)
    apps = app_catalog.get_all_catalog_apps()
    assert len(apps) >= 100 + len(app_catalog.CURATED_APP_CATALOG)
    community = [a for a in apps if a.get("source_id") == "community_portainer"]
    assert all(a["trust"] == "community" for a in community)
    assert community[0]["default_port"] == 8000


def test_no_duplicate_when_the_url_is_already_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(app_catalog, "CATALOG_SOURCES_FILE", str(tmp_path / "sources.json"))
    with open(tmp_path / "sources.json", "w") as f:
        json.dump(
            [
                dict(app_catalog.DEFAULT_SOURCES[0]),
                {"id": "mine", "name": "Mine", "url": app_catalog.COMMUNITY_SOURCES[0]["url"], "enabled": True},
            ],
            f,
        )
    ids = [s["id"] for s in app_catalog.get_catalog_sources()]
    assert ids == ["builtin", "mine"]
