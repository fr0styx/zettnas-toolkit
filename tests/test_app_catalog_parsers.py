"""Turning third-party app templates (Portainer style) into catalog entries: categories,
ports, volumes and environment."""

import pytest

from backend.services.app_catalog import (
    normalize_category,
    parse_portainer_env,
    parse_portainer_ports,
    parse_portainer_volumes,
)


@pytest.mark.parametrize(
    ("cats", "want"),
    [
        (["Media Servers"], "media"),
        ("TV", "media"),
        (["Photos"], "photos"),
        (["Backup", "Sync"], "cloud"),
        (["Home Automation"], "automation"),
        (["AI", "Chat"], "automation"),
        (["Downloaders"], "downloads"),
        (["Sonarr"], "downloads"),
        (["NZBGet"], "downloads"),
        (["Network", "DNS"], "utilities"),
        (["Development"], "utilities"),
        # short words inside other words used to decide the category
        (["Email"], "other"),
        (["Mail Server", "Container"], "other"),
        (["Maintenance"], "other"),
        (["Raid array"], "other"),
        ([], "other"),
        (None, "other"),
        (42, "other"),
    ],
)
def test_categories(cats, want):
    assert normalize_category(cats) == want


def test_ports_pick_the_web_port():
    port, ports = parse_portainer_ports(["9091:9091/tcp", "8096:8096/tcp"])
    assert port == 8096 and ports == ["9091:9091/tcp", "8096:8096/tcp"]
    port, ports = parse_portainer_ports(
        [{"container": 80, "host": 8088}, {"container": 53, "protocol": "udp"}, {"host": 1}]
    )
    assert port == 8088 and ports == ["8088:80/tcp", "53:53/udp"]
    assert parse_portainer_ports({"3000": "3001"}) == (3001, ["3001:3000"])
    assert parse_portainer_ports(["7000:7001"]) == (7000, ["7000:7001"])  # no known web port: the first
    assert parse_portainer_ports(["udp-only"]) == (8080, ["udp-only"])
    assert parse_portainer_ports(None) == (8080, [])


def test_volumes_from_each_template_form():
    assert parse_portainer_volumes([{"container": "/config"}, {"target": "/data/media"}]) == {
        "config": "/config",
        "media": "/data/media",
    }
    assert parse_portainer_volumes(["/mnt/a:/config", "/mnt/b:/downloads:ro"]) == {
        "config": "/config",
        "downloads": "/downloads",
    }
    assert parse_portainer_volumes({"appdata": "/config"}) == {"appdata": "/config"}
    assert parse_portainer_volumes([]) == {"config": "/config"}
    assert parse_portainer_volumes("nonsense") == {"config": "/config"}


def test_volumes_with_the_same_folder_name_both_stay():
    vols = parse_portainer_volumes(["/mnt/a:/srv/data", "/mnt/b:/var/data"])
    assert sorted(vols.values()) == ["/srv/data", "/var/data"]
    vols = parse_portainer_volumes([{"container": "/a/data"}, {"container": "/b/data"}])
    assert sorted(vols.values()) == ["/a/data", "/b/data"]
    # a relative container path is not a mount
    assert parse_portainer_volumes(["/mnt/a:relative"]) == {"config": "/config"}


def test_env_from_each_template_form():
    assert parse_portainer_env(
        [{"name": "TZ", "default": "UTC"}, {"name": "EMPTY", "default": None}, {"label": "x"}]
    ) == {
        "TZ": "UTC",
        "EMPTY": "",
    }
    assert parse_portainer_env(["PUID = 99", "bad", "URL=http://a=b"]) == {"PUID": "99", "URL": "http://a=b"}
    assert parse_portainer_env({"PGID": 100}) == {"PGID": "100"}
    assert parse_portainer_env(None) == {}
