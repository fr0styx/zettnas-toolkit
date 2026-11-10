"""RES-8: apps from Unraid templates, CasaOS and Umbrel apps, marked untested."""

import pytest

from backend.services import app_catalog
from backend.services import template_import as ti

UNRAID_XML = """<?xml version="1.0"?>
<Container version="2">
  <Name>jellyfin</Name>
  <Repository>lscr.io/linuxserver/jellyfin</Repository>
  <Network>bridge</Network>
  <Privileged>false</Privileged>
  <Overview>Volunteer-built [b]media[/b] server.</Overview>
  <Category>MediaServer:Video Status:Stable</Category>
  <WebUI>http://[IP]:[PORT:8096]/</WebUI>
  <Icon>https://example.org/jellyfin.png</Icon>
  <Config Name="WebUI" Target="8096" Default="8096" Mode="tcp" Type="Port">8096</Config>
  <Config Name="Appdata" Target="/config" Default="/mnt/user/appdata/jellyfin" Type="Path">/mnt/user/appdata/jellyfin</Config>
  <Config Name="Media" Target="/data/movies" Default="" Type="Path"/>
  <Config Name="PUID" Target="PUID" Default="99" Type="Variable">99</Config>
  <Config Name="TZ" Target="TZ" Default="Etc/UTC|Europe/Berlin" Type="Variable"/>
  <Config Name="GPU" Target="/dev/dri" Default="/dev/dri" Type="Device">/dev/dri</Config>
</Container>
"""

CASAOS = """
name: immich
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:v1.120.0
    ports: ["2283:2283"]
    volumes:
      - /DATA/AppData/$AppID/upload:/usr/src/app/upload
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      DB_HOSTNAME: database
      UPLOAD_LOCATION: /DATA/AppData/${AppID}/upload
  database:
    image: postgres:16
x-casaos:
  main: immich-server
  port_map: "2283"
  category: Gallery
  icon: https://example.org/immich.png
  title:
    en_us: Immich
    zh_cn: 相册
  tagline:
    en_us: Your photos at home
"""

UMBREL_COMPOSE = """
version: "3.7"
services:
  app_proxy:
    environment:
      APP_HOST: actual-budget_web_1
      APP_PORT: 5006
  web:
    image: actualbudget/actual-server:24.11.0@sha256:abc
    restart: on-failure
    user: "1000:1000"
    volumes:
      - ${APP_DATA_DIR}/data:/data
    environment:
      - PUID=1000
      - ACTUAL_DOMAIN=${DEVICE_DOMAIN_NAME}
"""
UMBREL_APP = "id: actual-budget\nname: Actual Budget\ntagline: Your money, your rules\ncategory: finance\nport: 5006\n"

PLAIN = "services:\n  whoami:\n    image: traefik/whoami\n    ports:\n      - 8000:80\n"


def test_an_unraid_template_becomes_an_app():
    kind, m = ti.convert(UNRAID_XML)
    assert kind == ti.UNRAID
    assert (m["name"], m["image"], m["default_port"]) == ("jellyfin", "lscr.io/linuxserver/jellyfin", 8096)
    assert set(m["volumes"].values()) == {"/config", "/data/movies"}  # where they live is Kiboto's choice
    assert m["env"] == {"PUID": "99", "TZ": "Etc/UTC"}
    assert m["category"] == "mediaserver"
    assert m["description"] == "Volunteer-built media server."
    assert m["flags"] == ["Uses the host device /dev/dri"]


def test_unraid_xml_with_entities_or_without_a_container_is_refused():
    with pytest.raises(ti.TemplateError, match="DOCTYPE"):
        ti.from_unraid(
            '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Container><Repository>&a;</Repository></Container>'
        )
    with pytest.raises(ti.TemplateError, match="no image"):
        ti.from_unraid("<Container><Name>x</Name></Container>")
    with pytest.raises(ti.TemplateError, match="no Unraid"):
        ti.from_unraid("<Containers><Other/></Containers>")
    with pytest.raises(ti.TemplateError, match="not valid XML"):
        ti.from_unraid("<Container><Name>")


def test_host_networking_and_privileged_are_flagged():
    xml = UNRAID_XML.replace("<Network>bridge", "<Network>host").replace("<Privileged>false", "<Privileged>true")
    assert {"Uses host networking", "Runs privileged"} <= set(ti.from_unraid(xml)["flags"])


def test_a_casaos_app_becomes_an_app():
    kind, m = ti.convert(CASAOS)
    assert kind == ti.CASAOS
    assert (m["name"], m["default_port"], m["category"]) == ("Immich", 2283, "gallery")
    assert list(m["volumes"].values()) == ["/usr/src/app/upload"]  # never the Docker socket
    assert m["env"]["UPLOAD_LOCATION"] == "/DATA/AppData//upload"  # the CasaOS variable is dropped
    assert "Asks for the Docker socket (left out)" in m["flags"]
    assert "Also needs database: only immich-server is imported" in m["flags"]
    assert m["description"] == "Your photos at home"


def test_an_umbrel_app_becomes_an_app():
    kind, m = ti.convert(UMBREL_COMPOSE, {"umbrel-app.yml": UMBREL_APP})
    assert kind == ti.UMBREL
    assert (m["name"], m["default_port"], m["category"]) == ("Actual Budget", 5006, "finance")
    assert m["image"].startswith("actualbudget/actual-server:24.11.0")
    assert list(m["volumes"].values()) == ["/data"]
    assert m["env"] == {"PUID": "99", "ACTUAL_DOMAIN": ""}  # Umbrel's own variables don't exist here


def test_plain_compose_and_nonsense():
    kind, m = ti.convert(PLAIN)
    assert (kind, m["name"], m["default_port"]) == (ti.COMPOSE, "whoami", 80)
    for bad, words in (
        ("hello", "not an Unraid"),
        ("services: [1]", "no service"),
        ("services:\n  a: {}\n", "no service"),
    ):
        with pytest.raises(ti.TemplateError, match=words):
            ti.convert(bad)
    with pytest.raises(ti.TemplateError, match="too big"):
        ti.convert("x" * (ti.MAX_BYTES + 1))
    with pytest.raises(ti.TemplateError, match="image name"):
        ti.convert("services:\n  a:\n    image: 'bad image; rm -rf'\n")
    with pytest.raises(ti.TemplateError, match="not valid YAML"):
        ti.convert("services:\n  a: [\n")


def test_which_text_is_foreign():
    assert ti.is_foreign(UNRAID_XML) and ti.is_foreign(CASAOS) and ti.is_foreign(UMBREL_COMPOSE)
    assert not ti.is_foreign(PLAIN) and not ti.is_foreign('{"name": "x"}')
    assert ti.is_store_folder("https://github.com/getumbrel/umbrel-apps/tree/master/actual-budget")
    assert not ti.is_store_folder("https://github.com/getumbrel/umbrel-apps/blob/master/x.yml")


def test_a_store_folder_is_read_as_its_compose_and_app_file(monkeypatch):
    seen = []

    def fake(url, **kw):
        seen.append(url)
        return (200, {}, (UMBREL_APP if url.endswith("umbrel-app.yml") else UMBREL_COMPOSE).encode())

    import backend.services.safe_fetch as sf

    monkeypatch.setattr(sf, "safe_fetch", fake)
    text, extra = ti.fetch("https://github.com/getumbrel/umbrel-apps/tree/master/actual-budget")
    assert seen == [
        "https://raw.githubusercontent.com/getumbrel/umbrel-apps/master/actual-budget/umbrel-app.yml",
        "https://raw.githubusercontent.com/getumbrel/umbrel-apps/master/actual-budget/docker-compose.yml",
    ]
    assert "app_proxy" in text and extra == {"umbrel-app.yml": UMBREL_APP}
    monkeypatch.setattr(sf, "safe_fetch", lambda url, **kw: (404, {}, b""))
    with pytest.raises(ti.TemplateError, match="HTTP 404"):
        ti.fetch("https://example.org/x.xml")
    with pytest.raises(ti.TemplateError, match="https"):
        ti.fetch("http://example.org/x.xml")


@pytest.fixture
def store(monkeypatch):
    saved = []
    monkeypatch.setattr(app_catalog, "get_sideloaded_apps", lambda: list(saved))
    monkeypatch.setattr(app_catalog, "save_sideloaded_apps", lambda items: saved.__setitem__(slice(None), items))
    return saved


def test_sideloading_a_template_marks_it_untested(store):
    res = app_catalog.sideload_app_manifest(manifest_content=UNRAID_XML)
    app = res["app"]
    assert app["untested"] is True and app["origin"] == "Unraid template"
    assert app["source_name"] == "Community: Unraid template, untested"
    assert app["image"] == "lscr.io/linuxserver/jellyfin"
    assert "Uses the host device /dev/dri" in res["security_flags"]
    assert app["raw_manifest"] == UNRAID_XML.strip()
    assert len(store) == 1


def test_a_plain_compose_sideload_is_unchanged(store):
    app = app_catalog.sideload_app_manifest(manifest_content=PLAIN)["app"]
    assert app["untested"] is False and app["source_name"] == "Sideloaded"
