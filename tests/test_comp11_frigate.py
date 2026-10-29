"""COMP-11: Frigate on the iGPU from the App Catalog, its detections as camera alerts."""

import time
import urllib.error

import pytest
import yaml

from backend.services import frigate_events as fe


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(fe, "SETTINGS_FILE", str(tmp_path / "frigate.json"))
    return tmp_path


def _ev(eid, camera="front", label="person", score=0.85, start=None, **kw):
    return {
        "id": eid,
        "camera": camera,
        "label": label,
        "start_time": start or time.time(),
        "data": {"top_score": score},
        "zones": kw.pop("zones", []),
        **kw,
    }


def test_settings_are_checked(cfg):
    assert fe.public()["enabled"] is False and fe.public()["url"] == fe.DEFAULT_URL
    with pytest.raises(ValueError, match="address"):
        fe.save_settings(url="ftp://frigate")
    with pytest.raises(ValueError, match="address"):
        fe.save_settings(url="http://frigate:5000/api/../x")
    with pytest.raises(ValueError, match="at least one"):
        fe.save_settings(labels=["unicorn"])
    with pytest.raises(ValueError, match="Camera names"):
        fe.save_settings(cameras=["front door"])
    s = fe.save_settings(enabled=True, labels=["car", "person", "car"], cameras=["front"], min_score=2, cooldown_min=0)
    assert s["labels"] == ["car", "person"] and s["min_score"] == 0.99 and s["cooldown_min"] == 1
    assert s["last_check"] > time.time() - 5  # turning it on starts from now, not from old events


def test_the_events_query(cfg):
    asked = []
    fe.fetch_events("http://frigate:5000", 1000.9, ["person", "car"], ["front"], get=lambda u: asked.append(u) or [])
    assert asked[0].startswith("http://frigate:5000/api/events?")
    assert "after=1000" in asked[0] and "labels=person%2Ccar" in asked[0] and "cameras=front" in asked[0]
    assert fe.fetch_events("http://x", 0, ["person"], [], get=lambda u: {"error": "x"}) == []


def test_pick_new_sure_and_outside_the_cooldown():
    s = {"min_score": 0.7, "cooldown_min": 5, "seen": ["old"], "last_sent": {}}
    now = time.time()
    events = [
        _ev("old"),
        _ev("a", start=now - 30),
        _ev("b", start=now - 20),  # same camera and object within the cooldown: one alert
        _ev("c", camera="back", label="car", score=0.6),  # not sure enough
        _ev("d", camera="back", label="dog", zones=["garden"]),
        _ev("e", false_positive=True),
        {"no": "id"},
    ]
    alerts, last_sent, seen = fe.pick(events, s, now)
    assert [a["title"] for a in alerts] == ["Person on front", "Dog on back"]
    assert (
        alerts[1]["message"].startswith("Frigate saw a dog on back in garden at ")
        and "85% sure" in alerts[1]["message"]
    )
    assert alerts[0]["type"] == "camera" and alerts[0]["dedup_key"] == "frigate:front:person"
    assert set(last_sent) == {"front:person", "back:dog"} and {"a", "b", "c", "d", "e"} <= set(seen)
    later, _, _ = fe.pick([_ev("f")], {**s, "last_sent": last_sent, "seen": seen}, now + 6 * 60)
    assert len(later) == 1


def test_scores_from_old_and_new_frigate():
    assert fe._score({"top_score": 0.5}) == 0.5
    assert fe._score({"data": {"score": 0.6}}) == 0.6
    assert fe._score({}) == 0.0


def test_tick_sends_and_remembers(cfg):
    fe.save_settings(enabled=True)
    now = time.time() + 1
    sent = []
    events = [_ev("1", start=now - 10), _ev("2", camera="drive", label="person", start=now - 5)]
    assert fe.tick(now, get=lambda u: events, send=sent.append) == 2
    assert fe.tick(now + 60, get=lambda u: events, send=sent.append) == 0  # already seen
    s = fe.settings()
    assert len(sent) == 2 and s["last_check"] == now + 60 and s["last_error"] == ""


def test_tick_off_or_unreachable(cfg):
    assert fe.tick(get=lambda u: pytest.fail("asked while off")) == 0
    fe.save_settings(enabled=True)

    def down(url):
        raise urllib.error.URLError("Name or service not known")

    assert fe.tick(get=down, send=lambda a: pytest.fail("sent")) == 0
    assert "didn't answer at http://frigate:5000" in fe.public()["last_error"]


def test_check_connection(cfg):
    answers = {
        "http://frigate:5000/api/config": {"cameras": {"front": {}, "back": {}}},
        "http://frigate:5000/api/version": "0.16.2-abc",
    }
    r = fe.check_connection(get=answers.__getitem__)
    assert r == {"ok": True, "version": "0.16.2-abc", "cameras": ["back", "front"]}

    def down(url):
        raise OSError("refused")

    assert fe.check_connection(get=down)["ok"] is False


def test_api(client, auth_headers, cfg, monkeypatch):
    got = client.get("/api/notifications/frigate", headers=auth_headers).json()
    assert got["enabled"] is False and "person" in got["choices"]
    r = client.put("/api/notifications/frigate", headers=auth_headers, json={"enabled": True, "labels": ["dog"]})
    assert r.status_code == 200 and r.json()["labels"] == ["dog"]
    assert (
        client.put("/api/notifications/frigate", headers=auth_headers, json={"url": "file:///etc"}).status_code == 400
    )
    monkeypatch.setattr(fe, "check_connection", lambda: {"ok": False, "error": "nope"})
    assert client.post("/api/notifications/frigate/test", headers=auth_headers).json()["ok"] is False


def test_camera_alerts_can_be_routed():
    from backend.services.notifications import ROUTABLE_EVENTS

    assert "camera" in ROUTABLE_EVENTS


def test_the_catalog_entry():
    from backend.services.catalog_templates import CURATED_APP_CATALOG, FRIGATE_YML

    app = next(a for a in CURATED_APP_CATALOG if a["id"] == "frigate")
    assert app["devices"] == ["/dev/dri"] and app["join_zettnas_network"] is True
    assert "5000" not in " ".join(app["ports"])  # the unauthenticated API stays on the inside
    conf = yaml.safe_load(FRIGATE_YML)
    assert conf["detectors"]["ov"] == {"type": "openvino", "device": "GPU"}
    assert conf["ffmpeg"]["hwaccel_args"] == "preset-vaapi"
    assert conf["cameras"]["example"]["enabled"] is False


def test_deploy_options(monkeypatch):
    from backend.services import app_catalog

    body = {"HostConfig": {}}
    app_catalog._apply_runtime_options(body, {"shm_size": 268435456})
    assert body["HostConfig"]["ShmSize"] == 268435456
    nets = {"NetworkSettings": {"Networks": {"bridge": {}, "zettnas_default": {}}}}
    monkeypatch.setattr(app_catalog, "_docker_request", lambda m, p: (200, nets))
    assert app_catalog._zettnas_network() == "zettnas_default"
    joined = {"HostConfig": {}}
    app_catalog._apply_runtime_options(joined, {"join_zettnas_network": True})
    assert joined["HostConfig"]["NetworkMode"] == "zettnas_default"
    kept = {"HostConfig": {"NetworkMode": "immich_net"}}
    app_catalog._apply_runtime_options(kept, {"join_zettnas_network": True})
    assert kept["HostConfig"]["NetworkMode"] == "immich_net"  # a stack's own network stays
    monkeypatch.setattr(
        app_catalog, "_docker_request", lambda m, p: (200, {"NetworkSettings": {"Networks": {"bridge": {}}}})
    )
    assert app_catalog._zettnas_network() is None  # names don't resolve on the default bridge
    monkeypatch.setattr(app_catalog, "_docker_request", lambda m, p: (404, {}))
    assert app_catalog._zettnas_network() is None

    def broken(m, p):
        raise OSError("no docker")

    monkeypatch.setattr(app_catalog, "_docker_request", broken)
    assert app_catalog._zettnas_network() is None


def test_frigate_deploys_on_zettnas_network(tmp_path, monkeypatch):
    import os

    from backend.services import app_catalog
    from tests.test_m3_immich_stack import FakeDocker

    fake = FakeDocker()
    monkeypatch.setattr(app_catalog, "_docker_request", fake)
    monkeypatch.setattr(app_catalog, "check_port_available_detailed", lambda *a, **k: (True, None))
    monkeypatch.setattr(app_catalog, "_zettnas_network", lambda: "zettnas_default")
    events = list(app_catalog.stream_deploy_catalog_app("frigate", storage_root=str(tmp_path)))
    assert events[-1]["step"] == "success", events[-1]
    body = fake.created["frigate"]
    assert body["HostConfig"]["NetworkMode"] == "zettnas_default"
    assert body["HostConfig"]["ShmSize"] == 268435456
    with open(os.path.join(tmp_path, "frigate", "config", "config.yml"), encoding="utf-8") as f:
        assert "type: openvino" in f.read()


def test_the_events_api_over_http():
    import http.server
    import json
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"0.16.2" if self.path == "/api/version" else json.dumps([{"id": "x"}]).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_port}"
        assert fe._get_json(f"{base}/api/version") == "0.16.2"
        assert fe.fetch_events(base, 0, ["person"], []) == [{"id": "x"}]
    finally:
        srv.shutdown()
