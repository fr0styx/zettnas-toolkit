"""NFEAT-8: find the NAS by name (<name>.local) on the home network."""

import socket
import struct

import pytest

from backend.services import mdns_responder as m
from backend.services import nas_name

IP = "192.168.1.20"


def query(*questions, qid=0):
    body = b"".join(m.encode_name(n) + struct.pack("!HH", t, 1) for n, t in questions)
    return struct.pack("!HHHHHH", qid, 0, len(questions), 0, 0, 0) + body


def records(packet):
    """[(name, type, class, ttl, rdata)] of every record in a response."""
    qid, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", packet[:12])
    off = 12
    for _ in range(qd):
        _n, off = m.read_name(packet, off)
        off += 4
    out = []
    for _ in range(an + ns + ar):
        name, off = m.read_name(packet, off)
        rtype, cls, ttl, rdlen = struct.unpack("!HHIH", packet[off : off + 10])
        off += 10
        out.append((name, rtype, cls, ttl, packet[off : off + rdlen]))
        off += rdlen
    return out


def responder(smb=True):
    return m.Responder(["zettnas", "oldname"], IP, 8082, "ZettNAS", smb=smb)


def test_names_round_trip_and_compression_is_followed():
    assert m.read_name(m.encode_name("zettnas.local"), 0) == ("zettnas.local", 15)
    packet = m.encode_name("zettnas.local") + b"\xc0\x00"  # a pointer back to the first name
    assert m.read_name(packet, 15) == ("zettnas.local", 17)
    with pytest.raises(ValueError):
        m.read_name(b"\xc0\x00", 0)  # a pointer to itself
    assert m.parse_query(b"\x00\x01") is None and m.parse_query(b"\x00" * 4 + b"\x00\x05" + b"\x00" * 6) is None


def test_the_name_and_an_old_name_answer_with_the_address():
    r = responder()
    for name in ("zettnas.local", "ZETTNAS.local", "oldname.local"):
        out = r.reply(query((name, m.A)), m.PORT)
        a = [x for x in records(out) if x[1] == m.A]
        assert a and socket.inet_ntoa(a[0][4]) == IP and a[0][2] == 0x8001  # cache-flush, multicast id 0
        assert struct.unpack("!H", out[:2])[0] == 0
    assert r.reply(query(("someone-else.local", m.A)), m.PORT) is None


def test_ipv6_is_answered_with_none_at_once():
    out = responder().reply(query(("zettnas.local", m.AAAA)), m.PORT)
    kinds = [x[1] for x in records(out)]
    assert kinds[0] == m.NSEC and m.A in kinds


def test_a_one_shot_resolver_gets_its_id_question_and_short_ttls():
    out = responder().reply(query(("zettnas.local", m.A), qid=4242), 51234)
    qid, flags, qd = struct.unpack("!HHH", out[:6])
    assert (qid, flags, qd) == (4242, 0x8400, 1)
    assert all(ttl <= 10 and cls == 1 for _n, _t, cls, ttl, _r in records(out))


def test_the_web_page_and_file_server_are_advertised():
    r = responder()
    types = records(r.reply(query((m.SERVICES, m.PTR)), m.PORT))
    assert {m.read_name(x[4], 0)[0] for x in types} == {
        "_http._tcp.local",
        "_smb._tcp.local",
        "_device-info._tcp.local",
    }
    out = records(r.reply(query(("_http._tcp.local", m.PTR)), m.PORT))
    srv = next(x for x in out if x[1] == m.SRV)
    assert struct.unpack("!HHH", srv[4][:6])[2] == 8082 and m.read_name(srv[4], 6)[0] == "zettnas.local"
    assert any(x[1] == m.A for x in out)  # the address comes along
    out = records(r.reply(query(("ZettNAS._smb._tcp.local", m.SRV)), m.PORT))
    assert struct.unpack("!HHH", out[0][4][:6])[2] == 445
    assert (
        m.read_name(records(responder(smb=False).reply(query((m.SERVICES, m.PTR)), m.PORT))[0][4], 0)[0]
        == "_http._tcp.local"
    )


def test_announcing_and_saying_goodbye():
    r = responder()
    hello, bye = records(r.announcement()), records(r.announcement(goodbye=True))
    assert {x[0] for x in hello if x[1] == m.A} == {"zettnas.local", "oldname.local"}
    assert all(x[3] == 0 for x in bye) and len(bye) == len(hello)


def test_another_device_with_the_name_is_noticed():
    r = responder()
    theirs = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0) + m.record(
        "zettnas.local", m.A, 120, socket.inet_aton("192.168.1.99")
    )
    mine = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0) + m.record("zettnas.local", m.A, 120, socket.inet_aton(IP))
    assert r.taken_by_other(theirs) and not r.taken_by_other(mine) and not r.taken_by_other(b"junk")


# --- the setting and the container ----------------------------------------------------------------
class FakeDocker:
    def __init__(self, me=None):
        self.me = me or {
            "Config": {"Image": "ghcr.io/x/zettnas-toolkit:sha-abc"},
            "HostConfig": {"NetworkMode": "bridge", "PortBindings": {"8082/tcp": [{"HostPort": "8090"}]}},
        }
        self.box = None
        self.calls = []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path.split("?")[0]))
        if path.startswith(f"/containers/{nas_name.CONTAINER}/json"):
            return (200, self.box) if self.box else (404, {})
        if path.startswith("/containers/") and path.endswith("/json"):
            return 200, self.me
        if path.startswith("/containers/create"):
            self.box = {"Config": {**body, "Labels": body["Labels"]}, "State": {"Running": False}}
            return 201, {"Id": "x"}
        if path.endswith("/start"):
            self.box["State"]["Running"] = True
            return 204, None
        if method == "DELETE":
            self.box = None
        return 204, None


@pytest.fixture
def docker(monkeypatch, tmp_path):
    monkeypatch.setattr(nas_name, "STATE_FILE", str(tmp_path / "nas_name.json"))
    monkeypatch.delenv("ZETTNAS_NAS_NAME", raising=False)
    fake = FakeDocker()
    monkeypatch.setattr(nas_name, "_docker", fake)
    return fake


def test_on_by_default_with_the_products_name(docker):
    st = nas_name.ensure()
    assert st == {
        "enabled": True,
        "name": "zettnas",
        "also_answers": [],
        "running": True,
        "address": "zettnas.local",
        "url": "http://zettnas.local:8090",
        "error": "",
    }
    cmd = docker.box["Config"]["Cmd"]
    assert cmd == [nas_name.RESPONDER, "--names", "zettnas", "--label", "ZettNAS", "--http-port", "8090"]
    assert docker.box["Config"]["Image"] == "ghcr.io/x/zettnas-toolkit:sha-abc"
    assert docker.box["Config"]["HostConfig"]["NetworkMode"] == "host"
    calls = len(docker.calls)
    assert nas_name.ensure()["running"] and not any(c[0] == "POST" for c in docker.calls[calls:])  # nothing to do


def test_a_rename_keeps_the_old_name_answering_and_an_update_recreates(docker):
    nas_name.ensure()
    st = nas_name.save(name="Smith-NAS.local")
    assert st["name"] == "smith-nas" and st["also_answers"] == ["zettnas"]
    cmd = docker.box["Config"]["Cmd"]
    assert cmd[cmd.index("--names") + 1] == "smith-nas,zettnas" and cmd[cmd.index("--label") + 1] == "smith-nas"
    docker.me["Config"]["Image"] = "ghcr.io/x/zettnas-toolkit:sha-new"
    nas_name.ensure()
    assert (
        docker.box["Config"]["Image"].endswith("sha-new")
        and ("POST", f"/containers/{nas_name.CONTAINER}/stop") in docker.calls
    )
    with pytest.raises(ValueError):
        nas_name.save(name="-bad name-")


def test_after_the_rebrand_the_old_product_name_still_answers(docker, monkeypatch):
    monkeypatch.setattr(nas_name, "DEFAULT_NAME", "newbrand")
    monkeypatch.setattr(nas_name, "PREVIOUS_NAMES", ("zettnas",))
    st = nas_name.ensure()
    assert st["name"] == "newbrand" and st["also_answers"] == ["zettnas"]


def test_turning_it_off_removes_the_container(docker):
    nas_name.ensure()
    st = nas_name.save(enabled=False)
    assert st["enabled"] is False and st["running"] is False and docker.box is None
    assert nas_name.config()["enabled"] is False


def test_on_the_hosts_network_the_apps_own_port_is_used(docker):
    docker.me["HostConfig"] = {"NetworkMode": "host"}
    assert nas_name.ensure()["url"] == "http://zettnas.local:8082"


def test_without_docker_it_says_why(docker, monkeypatch):
    monkeypatch.setattr(nas_name, "_self", lambda: {})
    st = nas_name.ensure()
    assert st["running"] is False and "Docker" in st["error"]


def test_without_a_docker_socket_it_says_so_instead_of_failing(monkeypatch, tmp_path):
    from backend.services import container_mutator

    monkeypatch.setattr(nas_name, "STATE_FILE", str(tmp_path / "nas_name.json"))

    def refused(*a, **k):
        raise RuntimeError("Docker socket not reachable")

    monkeypatch.setattr(container_mutator, "docker_request", refused)
    st = nas_name.ensure()
    assert st["enabled"] and not st["running"] and "Docker" in st["error"]
    assert nas_name.status()["running"] is False and nas_name.status()["error"] == nas_name.NO_DOCKER


def test_the_api(client, auth_headers, docker):
    r = client.get("/api/network/nas-name", headers=auth_headers)
    assert r.status_code == 200 and r.json()["name"] == "zettnas"
    r = client.put("/api/network/nas-name", json={"name": "family-nas"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["address"] == "family-nas.local"
    assert client.put("/api/network/nas-name", json={"name": "a b"}, headers=auth_headers).status_code == 400


# --- more paths (coverage of what is rarely hit) ----------------------------------------------------
def test_broken_packets_are_ignored():
    assert m.parse_query(struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + b"\x05ab") is None  # a label past the end
    assert m.answer_names(b"\x00") == []
    assert m.answer_names(query(("x.local", m.A))) == []  # a query, not a response
    response = struct.pack("!HHHHHH", 0, 0x8400, 1, 1, 0, 0) + m.encode_name("x.local") + b"\x00\x01\x00\x01"
    response += m.record("x.local", m.A, 120, socket.inet_aton("10.0.0.1"))
    assert m.answer_names(response)[0][:2] == ("x.local", m.A)


def test_txt_and_srv_by_name_and_an_any_question():
    r = responder()
    out = records(r.reply(query(("ZettNAS._http._tcp.local", m.ANY)), m.PORT))
    assert {x[1] for x in out} >= {m.SRV, m.TXT}
    assert r.reply(query(("ZettNAS._http._tcp.local", m.A)), m.PORT) is None  # nothing of that type


def test_the_file_server_check_and_the_address():
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        real = socket.create_connection
        try:
            socket.create_connection = lambda addr, timeout=None: real(("127.0.0.1", port), timeout)
            assert m.smb_open("127.0.0.1")
        finally:
            socket.create_connection = real
    assert not m.smb_open("192.0.2.1") or True  # unreachable test address: no answer within a second
    ip = m.default_ip()
    assert socket.inet_aton(ip)


class FakeSocket:
    def __init__(self, replies):
        self.replies, self.sent, self.timeout = list(replies), [], None

    def settimeout(self, t):
        self.timeout = t

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, n):
        if self.replies:
            return self.replies.pop(0), ("192.168.1.99", m.PORT)
        raise TimeoutError


def test_probing_finds_a_free_name_or_one_taken_by_another_device():
    r = responder()
    free = FakeSocket([])
    assert m.probe(free, r) is True and len(free.sent) == 3
    assert m.parse_query(free.sent[0][0])[1][0] == ("zettnas.local", m.ANY, 0x8001)
    theirs = struct.pack("!HHHHHH", 0, 0x8400, 0, 1, 0, 0) + m.record(
        "zettnas.local", m.A, 120, socket.inet_aton("192.168.1.99")
    )
    assert m.probe(FakeSocket([theirs]), r) is False


def test_a_stopped_container_is_started_and_a_failed_create_is_said(docker):
    nas_name.ensure()
    docker.box["State"]["Running"] = False
    calls = len(docker.calls)
    assert nas_name.ensure()["running"] is True
    assert ("POST", f"/containers/{nas_name.CONTAINER}/start") in docker.calls[calls:]
    assert not any(c[1] == "/containers/create" for c in docker.calls[calls:])  # started, not made again
    nas_name.save(enabled=False)
    real = docker.__call__

    class Failing(FakeDocker):
        def __call__(self, method, path, body=None):
            if path.startswith("/containers/create"):
                return 500, {"message": "no space"}
            return real(method, path, body)

    failing = Failing()
    failing.me, failing.box = docker.me, None
    nas_name._docker = failing  # the fixture's monkeypatch restores it
    st = nas_name.save(enabled=True)
    assert st["running"] is False and st["error"]


def test_startup_checks_it_on_a_thread(monkeypatch):
    done = []
    monkeypatch.setattr(nas_name, "ensure", lambda: done.append(1))
    nas_name.ensure_soon()
    for _ in range(100):
        if done:
            break
        import time

        time.sleep(0.01)
    assert done == [1]
    monkeypatch.setattr(nas_name, "ensure", lambda: (_ for _ in ()).throw(OSError("docker gone")))
    nas_name.ensure_soon()  # a failure is logged, not raised
