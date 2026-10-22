"""SEC-09: the Docker API proxy forwards only allow-listed calls."""

import asyncio
import glob
import json
import os
import re
import tempfile

import pytest

from backend import docker_proxy as dp

DOCKER_PREFIXES = (
    "/containers",
    "/images",
    "/networks",
    "/volumes",
    "/exec",
    "/info",
    "/version",
    "/_ping",
    "/events",
    "/system/df",
    "/distribution",
    "/build",
)


def _backend_docker_calls():
    pats = [
        re.compile(r'\(\s*"(GET|POST|DELETE|HEAD|PUT)",\s*f?"(/[^"?]+)'),
        re.compile(r'client\.(get|post|delete)\(\s*f?"(?:http://(?:docker|localhost))?(/[^"?]+)'),
        re.compile(r'f?"(GET|POST|DELETE|HEAD) (/[^ ?"]+)[^"]* HTTP/1\.1'),
    ]
    calls = set()
    for p in glob.glob("backend/**/*.py", recursive=True):
        if p.endswith("docker_proxy.py"):
            continue
        with open(p, encoding="utf-8") as f:
            src = f.read()
        for rx in pats:
            for m in rx.finditer(src):
                method, path = m.group(1).upper(), m.group(2)
                if path.startswith(DOCKER_PREFIXES):
                    path = path.replace("{action}", "start")
                    calls.add((method, re.sub(r"\{[^}]+\}", "x", path), p))
    return calls


def test_every_docker_call_the_backend_makes_is_allowed():
    calls = _backend_docker_calls()
    assert len(calls) > 40
    blocked = sorted(c for c in calls if not dp.endpoint_allowed(c[0], c[1]))
    assert blocked == []


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/swarm/init"),
        ("GET", "/secrets"),
        ("POST", "/plugins/pull"),
        ("POST", "/images/load"),
        ("POST", "/commit"),
        ("GET", "/containers/abc/export"),
        ("PUT", "/containers/abc/../archive"),
        ("POST", "/build"),
        ("POST", "/session"),
        ("GET", "/services"),
    ],
)
def test_dangerous_endpoints_are_denied(method, path):
    assert not dp.endpoint_allowed(method, path)


def test_paths_that_could_confuse_routing_are_rejected():
    for t in ("/containers/x/../../swarm/init", "/containers/x%2F..%2Fswarm", "//swarm", "/containers/./json"):
        assert dp.normalize_path(t) is None
    assert dp.normalize_path("/v1.43/containers/json?all=1") == ("/containers/json", "all=1")


def test_elevated_settings_are_detected():
    r = dp.elevated_reasons
    assert r("/containers/create", {"HostConfig": {"Privileged": True}}) == ["privileged"]
    assert r("/containers/create", {"HostConfig": {"Binds": ["/var/run/docker.sock:/var/run/docker.sock"]}})
    assert r("/containers/create", {"HostConfig": {"Binds": ["/:/host"]}})
    assert r("/containers/create", {"HostConfig": {"Binds": ["/boot/config:/cfg:ro"]}})
    assert r("/containers/create", {"HostConfig": {"Devices": [{"PathOnHost": "/dev/sda"}]}})
    assert r("/containers/create", {"HostConfig": {"CapAdd": ["SYS_ADMIN"], "PidMode": "host"}}) == [
        "PidMode=host",
        "cap SYS_ADMIN",
    ]
    assert r("/containers/abc/exec", {"Privileged": True}) == ["privileged exec"]
    ordinary = {
        "HostConfig": {
            "NetworkMode": "host",
            "CapAdd": ["NET_ADMIN"],
            "Binds": [
                "/mnt/user/media:/media",
                "appdata:/config",
                "/etc/localtime:/etc/localtime:ro",
                "/dev/dri:/dev/dri",
            ],
            "Devices": [{"PathOnHost": "/dev/dri/renderD128"}, {"PathOnHost": "/dev/net/tun"}],
        }
    }
    assert r("/containers/create", ordinary) == []


class _FakeDocker:
    def __init__(self):
        self.requests = []

    async def handle(self, r, w):
        head = await r.readuntil(b"\r\n\r\n")
        lines = head.decode().split("\r\n")
        hdrs = {k.lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:] if ln)}
        body = await r.readexactly(int(hdrs.get("content-length", 0)))
        self.requests.append((lines[0], hdrs, body))
        out = b'{"ok":true}'
        w.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n%s" % (len(out), out))
        await w.drain()
        w.close()


def test_proxy_forwards_allowed_and_refuses_the_rest(monkeypatch):
    import httpx

    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    up, listen = os.path.join(tmp, "up.sock"), os.path.join(tmp, "proxy.sock")
    fake = _FakeDocker()

    async def scenario():
        upstream = await asyncio.start_unix_server(fake.handle, path=up)
        proxy = await dp.serve(listen, up)
        results = {}
        async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=listen), base_url="http://docker") as c:
            results["list"] = (await c.get("/v1.43/containers/json?all=1")).status_code
            results["swarm"] = await c.post("/swarm/init", json={})
            results["priv"] = await c.post(
                "/containers/create?name=x", json={"Image": "a", "HostConfig": {"Privileged": True}}
            )
            results["priv_ok"] = (
                await c.post(
                    "/containers/create?name=x",
                    json={"Image": "a", "HostConfig": {"Privileged": True}},
                    headers={"X-ZettNAS-Elevated": "1"},
                )
            ).status_code
            results["import"] = (await c.post("/images/create?fromSrc=-")).status_code
            results["plain"] = (await c.post("/containers/create?name=y", json={"Image": "nginx"})).status_code
        proxy.close()
        upstream.close()
        return results

    res = asyncio.run(scenario())
    assert res["list"] == 200 and res["plain"] == 200 and res["priv_ok"] == 200
    assert res["swarm"].status_code == 403 and "not allowed" in res["swarm"].json()["message"]
    assert res["priv"].status_code == 403 and "privileged" in res["priv"].json()["message"]
    assert res["import"] == 403
    seen = [r[0] for r in fake.requests]
    assert not any("swarm" in s or "fromSrc" in s for s in seen)
    assert len(seen) == 3
    assert all(r[1].get("connection") == "close" for r in fake.requests)
    assert all("x-zettnas-elevated" not in r[1] for r in fake.requests)
    with open(os.path.join(tmp, "docker-proxy-audit.log")) as f:
        audit = [json.loads(ln) for ln in f]
    assert audit[0]["reasons"] == ["privileged"] and audit[0]["image"] == "a"


def test_docker_sock_follows_the_proxy(monkeypatch):
    from backend import config

    monkeypatch.delenv("ZETTNAS_DOCKER_SOCK", raising=False)
    assert config.docker_sock() == "/var/run/docker.sock"
    monkeypatch.setenv("ZETTNAS_DOCKER_SOCK", "/run/zettnas/docker.sock")
    assert config.docker_sock() == "/run/zettnas/docker.sock"
