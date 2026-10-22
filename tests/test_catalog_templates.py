"""Built-in App Catalog templates (backend/services/catalog_templates.py) and the deploy helpers."""

import re

import pytest

from backend.services import app_catalog
from backend.services.catalog_templates import CURATED_APP_CATALOG

CATEGORIES = {
    "media",
    "photos",
    "cloud",
    "productivity",
    "automation",
    "network",
    "monitoring",
    "downloads",
    "dev",
    "ai",
    "games",
    "utilities",
}
PORT_RE = re.compile(r"^(\d+):(\d+)(/(tcp|udp))?$")
SECRET_RE = re.compile(r"\{\{secret:([a-z0-9_]+)\}\}")


def test_ids_are_unique_and_there_are_plenty():
    ids = [a["id"] for a in CURATED_APP_CATALOG]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 75


@pytest.mark.parametrize("app", CURATED_APP_CATALOG, ids=lambda a: a["id"])
def test_template_is_complete(app):
    for key in ("id", "name", "category", "description", "image", "default_port", "env", "volumes"):
        assert key in app, key
    assert app["category"] in CATEGORIES
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", app["id"])
    assert ":" in app["image"].rsplit("/", 1)[-1], "pin a tag"
    assert 1 <= int(app["default_port"]) <= 65535
    for p in app.get("ports", []):
        assert PORT_RE.match(p), p
    if app.get("ports"):  # the suggested port must be one of the mappings
        assert any(
            int(PORT_RE.match(p).group(1)) == app["default_port"]
            or int(PORT_RE.match(p).group(2)) == app["default_port"]
            for p in app["ports"]
        )
    for vol, target in app["volumes"].items():
        assert re.fullmatch(r"[a-z0-9_.-]+", vol) and target.startswith("/")
    for vol in app.get("seed_files", {}):
        assert vol in app["volumes"]
    assert app.get("logo", "").startswith("https://")
    assert app.get("webui_scheme", "http") in ("http", "https")
    if app.get("webui_path") is None:
        assert app.get("probe") == "tcp"
    # every secret the credentials mention is one the app actually uses
    used = set(SECRET_RE.findall(str(app["env"]) + str(app.get("stack_services", {}))))
    shown = set(SECRET_RE.findall(str(app.get("credentials", {}))))
    assert shown <= used


def test_reverse_proxies_publish_http_and_https():
    by_id = {a["id"]: a for a in CURATED_APP_CATALOG}
    for pid in ("caddy", "nginx-proxy-manager"):
        hosts = {p.split(":")[0] for p in by_id[pid]["ports"]}
        assert {"80", "443"} <= hosts, pid


def test_seed_files_are_written_once_and_stay_inside(tmp_path):
    app = {
        "volumes": {"etc": "/etc/caddy"},
        "seed_files": {"etc": {"Caddyfile": "first", "../escape": "x", "sub/a.txt": "deep"}},
    }
    app_catalog._write_seed_files(app, str(tmp_path))
    assert (tmp_path / "etc" / "Caddyfile").read_text() == "first"
    assert (tmp_path / "etc" / "sub" / "a.txt").read_text() == "deep"
    assert not (tmp_path / "escape").exists()
    (tmp_path / "etc" / "Caddyfile").write_text("edited by the user")
    app_catalog._write_seed_files(app, str(tmp_path))
    assert (tmp_path / "etc" / "Caddyfile").read_text() == "edited by the user"


def test_runtime_options_only_pass_devices_the_host_has(monkeypatch):
    monkeypatch.setattr(app_catalog.os.path, "exists", lambda p: p == "/dev/dri")
    body = {"HostConfig": {}}
    app_catalog._apply_runtime_options(
        body,
        {
            "command": ["serve"],
            "cap_add": ["NET_ADMIN"],
            "sysctls": {"net.ipv4.ip_forward": 1},
            "devices": ["/dev/dri", "/dev/kvm", "/etc/passwd"],
        },
    )
    assert body["Cmd"] == ["serve"]
    assert body["HostConfig"]["CapAdd"] == ["NET_ADMIN"]
    assert body["HostConfig"]["Sysctls"] == {"net.ipv4.ip_forward": "1"}
    assert body["HostConfig"]["Devices"] == [
        {"PathOnHost": "/dev/dri", "PathInContainer": "/dev/dri", "CgroupPermissions": "rwm"}
    ]


def test_catalog_lists_stacks_and_hides_starter_files():
    apps = {a["id"]: a for a in app_catalog.get_all_catalog_apps() if a.get("source_id") == "builtin"}
    assert apps["immich"]["type"] == "stack"
    assert apps["jellyfin"]["type"] == "standalone"
    assert "seed_files" not in apps["caddy"]
    assert "seed_files" in next(a for a in CURATED_APP_CATALOG if a["id"] == "caddy")


def test_volume_owner_hands_new_folders_to_the_app_user(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(app_catalog.os, "chown", lambda p, u, g: calls.append((p.replace(str(tmp_path), ""), u, g)))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "settings.js").write_text("x")
    app = {"volumes": {"data": "/data"}, "volume_owner": "1000:1000", "seed_files": {"data": {"settings.js": "x"}}}
    app_catalog._own_volumes(app, str(tmp_path))
    assert calls == [("/data", 1000, 1000), ("/data/settings.js", 1000, 1000)]
    calls.clear()
    app_catalog._own_volumes({"volumes": {"data": "/data"}, "volume_owner": "root"}, str(tmp_path))
    assert calls == []


def test_templates_that_run_as_a_user_own_their_folders():
    by_id = {a["id"]: a for a in CURATED_APP_CATALOG}
    assert by_id["nodered"]["volume_owner"] == "1000:1000"
    assert by_id["n8n"]["volume_owner"] == "1000:1000"
    assert by_id["grafana"]["volume_owner"] == "472:0"
