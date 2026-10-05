"""Input guards on the HTTP API: path containment, uploads, schemas, legacy routes."""

import base64
import io
import os

import pytest
from PIL import Image
from test_api_auth import assert_error


def png_data_url(size=(4, 4), fmt="PNG"):
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 200, 120)).save(buf, format=fmt)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


# ---- folder browser / mkdir / copy destination ----


def test_browse_defaults_to_first_root(client, auth_headers, pool_tree):
    r = client.get("/api/browse?dirs_only=1", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["current"] == os.path.realpath(pool_tree)
    names = [d["name"] for d in body["dirs"]]
    assert "media" in names and ".." not in names  # no parent entry at a root
    assert "escape" not in names  # escaping symlink hidden


def test_browse_subdir_has_parent_entry(client, auth_headers, pool_tree):
    r = client.get(f"/api/browse?path={pool_tree}/media", headers=auth_headers)
    assert r.json()["dirs"][0]["name"] == ".."


@pytest.mark.parametrize("path", ["/", "/etc", "{pool}/../outside", "{pool}/escape/secret"])
def test_browse_outside_roots_forbidden(client, auth_headers, pool_tree, path):
    r = client.get("/api/browse", params={"path": path.format(pool=pool_tree)}, headers=auth_headers)
    assert_error(r, 403, "forbidden")


def test_browse_missing_path_404(client, auth_headers, pool_tree):
    assert_error(client.get("/api/browse", params={"path": f"{pool_tree}/nope"}, headers=auth_headers), 404)


def test_browse_file_is_not_a_directory(client, auth_headers, pool_tree):
    r = client.get("/api/browse", params={"path": f"{pool_tree}/media/readme.txt"}, headers=auth_headers)
    assert_error(r, 400)


def test_mkdir_inside_root(client, auth_headers, pool_tree):
    target = f"{pool_tree}/backups/2026"
    r = client.post("/api/mkdir", json={"path": target}, headers=auth_headers)
    assert r.status_code == 200 and os.path.isdir(target)


@pytest.mark.parametrize("path", ["/tmp/zett-evil", "{pool}/../evil", "{pool}/escape/evil"])
def test_mkdir_outside_root_forbidden(client, auth_headers, pool_tree, path):
    r = client.post("/api/mkdir", json={"path": path.format(pool=pool_tree)}, headers=auth_headers)
    assert_error(r, 403)


def test_mkdir_legacy_get_removed(client, auth_headers, pool_tree):
    r = client.get("/api/mkdir", params={"path": f"{pool_tree}/x"}, headers=auth_headers)
    assert r.status_code in (404, 405)
    assert not os.path.exists(f"{pool_tree}/x")


def test_button_dest_must_be_inside_root(client, auth_headers, pool_tree):
    assert_error(client.post("/api/buttons", json={"dest": "/etc"}, headers=auth_headers), 403)
    ok = client.post("/api/buttons", json={"dest": f"{pool_tree}/media"}, headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["dest"] == os.path.realpath(f"{pool_tree}/media")


# ---- events ----


def test_events_clear_requires_delete(client, auth_headers):
    assert client.get("/api/events/clear", headers=auth_headers).status_code in (404, 405)
    assert client.post("/api/events/clear", headers=auth_headers).status_code in (404, 405)
    assert client.delete("/api/events/clear", headers=auth_headers).status_code == 200


# ---- wallpapers ----


def test_wallpaper_upload_select_download_delete(client, auth_headers):
    r = client.post(
        "/api/wallpapers/upload", headers=auth_headers, json={"image": png_data_url(), "filename": "../../My Pic!.jpg"}
    )
    assert r.status_code == 200, r.text
    name = r.json()["filename"]
    assert name == "My_Pic.png"  # basename only, extension from content
    d = client.get(f"/api/wallpapers/download/{name}")  # public for <img>/CSS
    assert d.status_code == 200
    assert d.headers["content-type"] == "image/png"
    assert d.headers["x-content-type-options"] == "nosniff"
    # UI sends `filename`; API also accepts `name`.
    assert client.post("/api/wallpapers/select", json={"filename": name}, headers=auth_headers).json()["success"]
    assert client.get("/api/wallpapers", headers=auth_headers).json()["active"] == name
    assert client.post("/api/wallpapers/select", json={"filename": None}, headers=auth_headers).json()["success"]
    assert client.delete(f"/api/wallpapers/{name}", headers=auth_headers).status_code == 200


def test_wallpaper_rejects_non_image(client, auth_headers):
    html = base64.b64encode(b"<html><script>alert(1)</script></html>").decode()
    r = client.post("/api/wallpapers/upload", headers=auth_headers, json={"image": html, "filename": "x.png"})
    assert_error(r, 415, "unsupported_media_type")
    assert r.json()["success"] is False


def test_wallpaper_rejects_oversized(client, auth_headers, monkeypatch):
    import backend.api.wallpapers as wp

    monkeypatch.setattr(wp, "MAX_WALLPAPER_BYTES", 10)
    r = client.post("/api/wallpapers/upload", headers=auth_headers, json={"image": png_data_url()})
    assert_error(r, 413)


def test_wallpaper_download_traversal_blocked(client):
    assert client.get("/api/wallpapers/download/..%2Fsecurity.json").status_code == 404
    assert client.get("/api/wallpapers/download/security.json").status_code == 404


def test_wallpaper_rename_keeps_verified_extension(client, auth_headers):
    name = client.post(
        "/api/wallpapers/upload", headers=auth_headers, json={"image": png_data_url(), "filename": "orig.png"}
    ).json()["filename"]
    r = client.post("/api/wallpapers/rename", headers=auth_headers, json={"old_name": name, "new_name": "evil.html"})
    assert r.status_code == 200
    assert r.json()["new_name"] == "evil_html.png"
    client.delete("/api/wallpapers/evil_html.png", headers=auth_headers)


# ---- schemas ----


def test_layout_roundtrip(client, auth_headers):
    payload = {
        "order": ["metric-cpu", "metric-mem"],
        "vis": {"metric-cpu": True},
        "sizes": {"metric-cpu": "compact", "metric-mem": "weird"},
        "clock_format": "12",
        "timezone": "America/New_York",
    }
    r = client.post("/api/layout", json=payload, headers=auth_headers)
    assert r.status_code == 200
    layout = r.json()["layout"]
    assert layout["sizes"] == {"metric-cpu": "compact"}  # unknown size dropped
    assert layout["version"] > 0
    assert client.get("/api/layout", headers=auth_headers).json()["clock_format"] == "12"


@pytest.mark.parametrize(
    "payload",
    [
        {"clock_format": "99"},
        {"timezone": "../../etc/passwd;rm"},
        {"order": "not-a-list"},
        {"order": ["x"] * 100},
    ],
)
def test_layout_rejects_bad_input(client, auth_headers, payload):
    assert_error(client.post("/api/layout", json=payload, headers=auth_headers), 422, "validation_error")


def test_fans_sanitizes_curve_and_validates_profile(client, auth_headers):
    r = client.post(
        "/api/fans", headers=auth_headers, json={"profile": "auto", "curve_points": [[60, 100], [30, 50], [45, 20]]}
    )
    assert r.status_code == 200
    assert r.json()["curve_points"] == [[30, 50], [45, 50], [60, 100]]
    assert_error(client.post("/api/fans", json={"profile": "turbo"}, headers=auth_headers), 400)


def test_fans_clamps_ranges(client, auth_headers):
    r = client.post("/api/fans", headers=auth_headers, json={"manual_pct": 500, "temp_min": 60, "temp_max": 40})
    body = r.json()
    assert body["manual_pct"] == 100
    assert body["temp_max"] > body["temp_min"]


def test_state_schema(client, auth_headers):
    assert client.post("/api/state", json={"fb": False}, headers=auth_headers).status_code == 200
    assert_error(client.post("/api/state", json={"fb": "maybe"}, headers=auth_headers), 422)


def test_disk_detail_rejects_injection(client, auth_headers):
    assert_error(client.get("/api/disk_detail", params={"dev": "sda;reboot"}, headers=auth_headers), 400)


def test_unknown_api_route_uses_error_schema(client, auth_headers):
    assert_error(client.get("/api/does-not-exist", headers=auth_headers), 404, "not_found")


def test_static_path_traversal_blocked(client):
    assert client.get("/..%2F..%2Fetc%2Fpasswd").status_code == 404
