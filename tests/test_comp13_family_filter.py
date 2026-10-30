"""COMP-13: the kids' devices filtered through AdGuard Home, one client per family account."""

import base64
import io
import json
import urllib.error

import pytest

from backend.services import adguard_kids as ak


class FakeAdGuard:
    """Answers /control/* like AdGuard Home, checking basic auth."""

    def __init__(self, password="pw"):
        self.password = password
        self.clients = {}
        self.calls = []

    def __call__(self, req, timeout=0):
        auth = base64.b64decode(req.get_header("Authorization").split()[1]).decode()
        if auth != f"admin:{self.password}":
            raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
        path = req.full_url.split("3000", 1)[1]
        body = json.loads(req.data) if req.data else None
        self.calls.append((req.get_method(), path))
        out = None
        if path == "/control/status":
            out = {"version": "v0.107.60", "protection_enabled": True}
        elif path == "/control/clients":
            out = {"clients": list(self.clients.values())}
        elif path == "/control/clients/add":
            self.clients[body["name"]] = body
        elif path == "/control/clients/update":
            self.clients[body["name"]] = body["data"]
        elif path == "/control/clients/delete":
            self.clients.pop(body["name"])
        return io.BytesIO(json.dumps(out).encode() if out is not None else b"OK")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ak, "SETTINGS_FILE", str(tmp_path / "adguard.json"))
    return tmp_path


def test_device_ids():
    assert ak.device_id(" 192.168.1.20 ") == "192.168.1.20"
    assert ak.device_id("fd00::5") == "fd00::5"
    assert ak.device_id("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    assert ak.device_id("kids-tablet") == "kids-tablet"
    for bad in ("", "1.2.3", "not a device", "x" * 80):
        with pytest.raises(ValueError):
            ak.device_id(bad)


def test_connection_is_kept_sealed(store):
    with pytest.raises(ValueError, match="address"):
        ak.save_connection(url="javascript:alert(1)")
    with pytest.raises(ValueError, match="user name"):
        ak.save_connection(user="a b")
    pub = ak.save_connection(url="http://adguardhome:3000/", user="admin", password="pw")
    assert pub == {"url": "http://adguardhome:3000", "user": "admin", "has_password": True, "people": {}}
    raw = json.loads((store / "adguard.json").read_text())
    assert raw["password"] != "pw" and raw["password"].startswith("enc")
    assert ak.save_connection(password="")["has_password"] is False


def test_check(store):
    assert ak.check(opener=FakeAdGuard())["ok"] is False  # not connected yet
    ak.save_connection(user="admin", password="pw")
    assert ak.check(opener=FakeAdGuard()) == {"ok": True, "version": "v0.107.60", "protection": True}
    bad = ak.check(opener=FakeAdGuard(password="other"))
    assert bad["ok"] is False and "refused" in bad["error"]

    def down(req, timeout=0):
        raise urllib.error.URLError("Name or service not known")

    assert "didn't answer" in ak.check(opener=down)["error"]


def test_a_person_filtered_changed_and_cleared(store):
    ak.save_connection(user="admin", password="pw")
    fake = FakeAdGuard()
    ak.set_person("mia", ["192.168.1.20", "AA:BB:CC:DD:EE:FF", "192.168.1.20"], ["tiktok"], opener=fake)
    c = fake.clients["ZettNAS: mia"]
    assert c["ids"] == ["192.168.1.20", "aa:bb:cc:dd:ee:ff"]
    assert c["parental_enabled"] and c["safebrowsing_enabled"] and c["safe_search"]["youtube"]
    assert c["blocked_services"] == ["tiktok"] and c["use_global_blocked_services"] is False
    assert ak.public()["people"]["mia"] == {"devices": ["192.168.1.20", "aa:bb:cc:dd:ee:ff"], "blocked": ["tiktok"]}
    ak.set_person("mia", ["192.168.1.21"], [], opener=fake)
    assert ("POST", "/control/clients/update") in fake.calls
    assert fake.clients["ZettNAS: mia"]["use_global_blocked_services"] is True
    ak.set_person("mia", [], [], opener=fake)
    assert fake.clients == {} and ak.public()["people"] == {}
    with pytest.raises(ValueError, match="can't block"):
        ak.set_person("mia", ["192.168.1.21"], ["everything"], opener=fake)
    with pytest.raises(ValueError, match="No such account"):
        ak.set_person("../x", [], [], opener=fake)


def test_adguard_errors(store):
    with pytest.raises(ak.AdGuardError, match="Connect AdGuard Home first"):
        ak.set_person("mia", ["192.168.1.20"], [], opener=FakeAdGuard())
    ak.save_connection(user="admin", password="pw")

    def broken(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

    with pytest.raises(ak.AdGuardError, match="answered 500"):
        ak.set_person("mia", ["192.168.1.20"], [], opener=broken)


def test_reseal(store):
    assert ak.reseal() == 0
    ak.save_connection(user="admin", password="pw")
    before = json.loads((store / "adguard.json").read_text())["password"]
    assert ak.reseal() == 1
    after = json.loads((store / "adguard.json").read_text())["password"]
    assert after != before
    from backend import secret_box

    assert secret_box.unseal(after) == "pw"


def test_api(client, auth_headers, store, monkeypatch):
    from backend.services import adguard_kids

    got = client.get("/api/family-filter", headers=auth_headers).json()
    assert got["has_password"] is False and "tiktok" in got["services"] and isinstance(got["accounts"], list)
    assert "password" not in got
    r = client.put("/api/family-filter/connection", headers=auth_headers, json={"user": "admin", "password": "pw"})
    assert r.status_code == 200 and r.json()["has_password"] is True
    assert client.put("/api/family-filter/connection", headers=auth_headers, json={"url": "ftp://x"}).status_code == 400
    monkeypatch.setattr(adguard_kids, "check", lambda: {"ok": True, "version": "v1"})
    assert client.post("/api/family-filter/check", headers=auth_headers).json()["version"] == "v1"
    assert client.put("/api/family-filter/people/nobody-here", headers=auth_headers, json={}).status_code == 404
    seen = []

    def fake_set(username, devices, blocked):
        seen.append((username, devices, blocked))
        if devices == ["bad"]:
            raise ValueError("bad isn't an IP address")
        if devices == ["down"]:
            raise adguard_kids.AdGuardError("AdGuard Home didn't answer")
        return adguard_kids.public()

    monkeypatch.setattr(adguard_kids, "set_person", fake_set)
    assert (
        client.put(
            "/api/family-filter/people/admin", headers=auth_headers, json={"devices": ["192.168.1.9"]}
        ).status_code
        == 200
    )
    assert (
        client.put("/api/family-filter/people/admin", headers=auth_headers, json={"devices": ["bad"]}).status_code
        == 400
    )
    assert (
        client.put("/api/family-filter/people/admin", headers=auth_headers, json={"devices": ["down"]}).status_code
        == 502
    )
    assert seen[0] == ("admin", ["192.168.1.9"], [])


def test_adguard_joins_zettnas_network():
    from backend.services.catalog_templates import CURATED_APP_CATALOG

    app = next(a for a in CURATED_APP_CATALOG if a["id"] == "adguardhome")
    assert app["join_zettnas_network"] is True


def test_kid_accounts_can_be_filtered(client, auth_headers, store, monkeypatch):
    """NSEC-12: Kid accounts are offered, not only family and guest ones."""
    monkeypatch.setattr(
        "backend.users_db.list_users",
        lambda: [{"username": "mia", "role_id": "kid"}, {"username": "dad", "role_id": "superadmin"}],
    )
    got = client.get("/api/family-filter", headers=auth_headers).json()
    assert [a["username"] for a in got["accounts"]] == ["mia"]
