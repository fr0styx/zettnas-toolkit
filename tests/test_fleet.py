"""RES-9 / COMP-14: Kiboto boxes paired over the tailnet, a summary of each, and buddy backups."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

from backend.services import fleet, fleet_buddy

A = "https://attic.example-tailnet.ts.net"
B = "http://100.101.102.103:8082"


class Boxes:
    """Two boxes in one test: each call to the other box runs that box's route code on its own state file."""

    def __init__(self, tmp_path, monkeypatch):
        self.files = {A: str(tmp_path / "a.json"), B: str(tmp_path / "b.json")}
        self.me = A
        self.calls = []
        monkeypatch.setattr(fleet, "STATE_FILE", self.files[A])
        monkeypatch.setattr(fleet, "my_address", lambda: self.me)
        monkeypatch.setattr(fleet, "my_name", lambda: "attic" if self.me == A else "cellar")
        monkeypatch.setattr(fleet, "audit", lambda *a: None)
        monkeypatch.setattr(fleet, "_NO_REDIRECTS", type("O", (), {"open": staticmethod(self)})())
        fleet._cache.clear()

    def be(self, who):
        self.me = who
        fleet.STATE_FILE = self.files[who]

    def __call__(self, req, timeout=10):
        url = req.full_url
        target = A if url.startswith(A) else B
        path = url[len(target) + len(fleet.PEER_PATH) :]
        body = json.loads(req.data) if req.data else {}
        auth = req.get_header("Authorization") or ""
        self.calls.append((target, path))
        caller = self.me
        self.be(target)
        try:
            if path == "/pair":
                out = fleet.accept_pairing(body["code"], body["box_id"], body["name"], body["address"], body["token"])
            else:
                box = fleet.peer_for_token(auth)
                if not box:
                    raise urllib.error.HTTPError(url, 401, "no", {}, io.BytesIO(b'{"detail":"Not a paired box."}'))
                if path == "/summary":
                    out = {"name": fleet.my_name(), "version": "2.0.0", "storage": [], "backups": []}
                elif path == "/unpair":
                    fleet.forget(box, tell=False)
                    out = {"ok": True}
                elif path == "/buddy":
                    out = fleet_buddy.give_space(box)
                else:
                    raise AssertionError(path)
        except fleet.FleetError as e:
            raise urllib.error.HTTPError(
                url, 403, "no", {}, io.BytesIO(json.dumps({"detail": str(e)}).encode())
            ) from None
        finally:
            self.be(caller)

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(json.dumps(out).encode())


@pytest.fixture
def boxes(tmp_path, monkeypatch):
    return Boxes(tmp_path, monkeypatch)


def _pair(boxes):
    boxes.be(A)
    code = fleet.new_code()["code"]
    boxes.be(B)
    st = fleet.pair_with(A, code)
    boxes.be(A)
    return code, st


def test_only_tailnet_addresses():
    assert fleet.on_tailnet("https://nas.example.ts.net")
    assert fleet.on_tailnet("http://100.64.0.9:8082")
    assert fleet.on_tailnet("http://[fd7a:115c:a1e0::5]:8082")
    for bad in (
        "https://example.com",
        "http://192.168.1.5:8082",
        "ftp://nas.example.ts.net",
        "https://nas.example.ts.net/x",
        "nope",
    ):
        assert not fleet.on_tailnet(bad), bad
    with pytest.raises(fleet.FleetError, match="Tailscale address"):
        fleet.pair_with("https://example.com", "AAAA-BBBB-CCCC-DDDD")


def test_pairing_both_ways_and_the_summary(boxes):
    _code, st = _pair(boxes)
    assert [p["name"] for p in st["peers"]] == ["attic"]  # B now knows A
    a_view = fleet.status(with_summaries=True)  # and A knows B, and can read B's summary
    assert [p["name"] for p in a_view["peers"]] == ["cellar"]
    assert a_view["peers"][0]["summary"]["name"] == "cellar"
    assert a_view["pairing_waiting"] is False  # the code was used up
    raw = Path(boxes.files[A]).read_text()
    assert "kbpeer-" not in raw and '"accept"' in raw  # the token sent is sealed, the one accepted hashed


def test_a_code_is_single_use_and_wrong_codes_run_out(boxes):
    boxes.be(A)
    code = fleet.new_code()["code"]
    boxes.be(B)
    for _ in range(fleet.CODE_TRIES):
        with pytest.raises(fleet.FleetError, match="wrong"):
            fleet.pair_with(A, "AAAA-BBBB-CCCC-DDDD")
    with pytest.raises(fleet.FleetError, match="No pairing code"):
        fleet.pair_with(A, code)  # five wrong tries end the code
    boxes.be(A)
    code = fleet.new_code()["code"]
    boxes.be(B)
    fleet.pair_with(A, code.lower().replace("-", " "))  # typed loosely still works
    with pytest.raises(fleet.FleetError, match="No pairing code"):
        fleet.pair_with(A, code)


def test_an_expired_code_and_no_tailscale(boxes, monkeypatch):
    boxes.be(A)
    code = fleet.new_code()["code"]
    data = fleet._state()
    data["pairing"]["expires"] = 0
    fleet._save(data)
    boxes.be(B)
    with pytest.raises(fleet.FleetError, match="ran out"):
        fleet.pair_with(A, code)
    monkeypatch.setattr(fleet, "my_address", lambda: "")
    with pytest.raises(fleet.FleetError, match="Connect Tailscale"):
        fleet.new_code()


def test_tokens_and_unpairing_on_both_sides(boxes):
    _pair(boxes)
    assert fleet.peer_for_token("Bearer nope") == ""
    assert fleet.peer_for_token("Bearer kbpeer-wrong") == ""
    b_id = fleet.status()["peers"][0]["id"]
    fleet.forget(b_id)
    assert fleet.status()["peers"] == []
    boxes.be(B)
    assert fleet.status()["peers"] == []  # B was told and forgot A
    with pytest.raises(KeyError):
        fleet.forget("0123456789abcdef", tell=False)


def test_an_unreachable_box_shows_why(boxes, monkeypatch):
    _pair(boxes)

    def down(req, timeout=10):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(fleet, "_NO_REDIRECTS", type("O", (), {"open": staticmethod(down)})())
    fleet._cache.clear()
    assert "didn't answer" in fleet.status(with_summaries=True)["peers"][0]["summary"]["error"]


def test_buddy_space_only_when_allowed(boxes, monkeypatch):
    _pair(boxes)
    containers = [
        {
            "Image": "restic/rest-server:latest",
            "Names": ["/rest-server"],
            "Ports": [{"PrivatePort": 8000, "PublicPort": 8000}],
        }
    ]
    made = []

    from backend.services import app_after_start, docker_client, offsite_backup

    monkeypatch.setattr(docker_client, "request", lambda m, p, *a, **k: (200, containers))
    monkeypatch.setattr(app_after_start, "exec_in", lambda c, cmd, **k: made.append((c, cmd)) or (0, ""))
    saved = {}
    monkeypatch.setattr(
        offsite_backup,
        "save_repo",
        lambda rid, name, loc, paths, **kw: saved.update(id=rid, name=name, loc=loc, paths=paths, **kw),
    )
    monkeypatch.setattr(offsite_backup, "init", lambda rid: saved.update(inited=rid))
    b_id = fleet.status()["peers"][0]["id"]
    boxes.be(B)
    a_id = fleet.status()["peers"][0]["id"]
    with pytest.raises(fleet.FleetError, match="hasn't allowed"):
        fleet_buddy.back_up_to(a_id, ["/mnt/user/photos"])
    boxes.be(A)
    fleet.set_offer(b_id, True)
    boxes.be(B)
    st = fleet_buddy.back_up_to(a_id, ["/mnt/user/photos"])
    assert made and made[0][0] == "rest-server" and made[0][1][:2] == ["create_user", fleet_buddy.account_for(b_id)]
    assert saved["loc"] == f"rest:http://attic.example-tailnet.ts.net:8000/{fleet_buddy.account_for(b_id)}/"
    assert saved["rest_user"] == fleet_buddy.account_for(b_id) and len(saved["rest_password"]) > 20
    assert saved["name"] == "Buddy: attic" and saved["inited"] == saved["id"]
    assert st["peers"][0]["backup_repo"] == saved["id"]
    containers.clear()
    with pytest.raises(fleet.FleetError, match="REST server"):
        fleet_buddy.back_up_to(a_id, ["/mnt/user/photos"])


def test_reseal(boxes):
    assert fleet.reseal() == 0
    _pair(boxes)
    assert fleet.reseal() == 1


def test_the_routes(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet, "STATE_FILE", str(tmp_path / "fleet.json"))
    monkeypatch.setattr(fleet, "my_address", lambda: A)
    monkeypatch.setattr(fleet, "audit", lambda *a: None)
    assert client.get("/api/fleet", headers=auth_headers).json()["peers"] == []
    code = client.post("/api/fleet/pairing", headers=auth_headers).json()["code"]
    assert len(code) == 19
    assert client.get("/api/fleet/peer/summary").status_code == 401
    assert client.get("/api/fleet/peer/summary", headers={"Authorization": "Bearer kbpeer-x"}).status_code == 401
    bad = {"code": "AAAA-BBBB-CCCC-DDDD", "box_id": "0123456789abcdef", "name": "x", "address": B, "token": "t" * 40}
    assert client.post("/api/fleet/peer/pair", json=bad).status_code == 403
    ok = client.post("/api/fleet/peer/pair", json={**bad, "code": code}).json()
    token = ok["token"]
    summary = client.get("/api/fleet/peer/summary", headers={"Authorization": f"Bearer kbpeer-{token}"})
    assert summary.status_code == 200 and "version" in summary.json() and "storage" in summary.json()
    res = client.post("/api/fleet/peer/buddy", headers={"Authorization": f"Bearer kbpeer-{token}"})
    assert res.status_code == 409  # not allowed yet
    assert (
        client.put("/api/fleet/peers/0123456789abcdef/offer", json={"enabled": False}, headers=auth_headers).status_code
        == 200
    )
    assert client.post("/api/fleet/peer/unpair", headers={"Authorization": f"Bearer kbpeer-{token}"}).json() == {
        "ok": True
    }
    assert client.delete("/api/fleet/peers/0123456789abcdef", headers=auth_headers).status_code == 404


@pytest.mark.real_confirmations
def test_pairing_and_giving_space_are_confirmed(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(fleet, "STATE_FILE", str(tmp_path / "fleet.json"))
    res = client.post("/api/fleet/peers", json={"address": A, "code": "AAAA-BBBB-CCCC-DDDD"}, headers=auth_headers)
    assert res.status_code == 428
    data = fleet._state()
    data["peers"]["0123456789abcdef"] = {"name": "cellar", "address": B, "send": "", "accept": "x"}
    fleet._save(data)
    res = client.put("/api/fleet/peers/0123456789abcdef/offer", json={"enabled": True}, headers=auth_headers)
    assert res.status_code == 428
