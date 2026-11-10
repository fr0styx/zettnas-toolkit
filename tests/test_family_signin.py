"""NFEAT-6: one family sign-in for the apps, Pocket ID run and filled by Kiboto."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

from backend.services import family_signin as fs

NAME = "attic.example-tailnet.ts.net"
REMOTE = {
    "name": NAME,
    "https": True,
    "addresses": {
        "immich": f"https://{NAME}:8443/",
        "apps": [
            {"name": "nextcloud", "url": f"https://{NAME}:18080/"},
            {"name": "jellyfin", "url": f"http://{NAME}:8096/"},
        ],
    },
}
ME = {
    "Config": {"Image": "ghcr.io/fr0styx/kiboto:latest"},
    "HostConfig": {"NetworkMode": "kiboto_default"},
    "Mounts": [{"Destination": "", "Type": "bind", "Source": "/mnt/user/appdata/kiboto"}],
}


class FakePocketId:
    def __init__(self):
        self.users, self.groups, self.clients, self.calls = {}, {}, {}, []
        self.n = 0

    def _id(self):
        self.n += 1
        return f"id{self.n}"

    def __call__(self, req, timeout=10):
        method, url = req.get_method(), req.full_url
        path = url.split(f":{fs.PORT}", 1)[1].split("?")[0]
        body = json.loads(req.data) if req.data else None
        self.calls.append((method, path, body, req.get_header("X-api-key")))
        out = None
        if path == "/api/users" and method == "GET":
            out = {"data": list(self.users.values()), "pagination": {"totalPages": 1}}
        elif path == "/api/users" and method == "POST":
            uid = self._id()
            self.users[uid] = {**body, "id": uid}
            out = self.users[uid]
        elif path.startswith("/api/users/") and path.endswith("/one-time-access-token"):
            out = {"token": "Tok123abc"}
        elif path.startswith("/api/users/") and method == "PUT":
            uid = path.rsplit("/", 1)[1]
            self.users[uid] = {**body, "id": uid}
            out = self.users[uid]
        elif path == "/api/user-groups" and method == "GET":
            out = {"data": list(self.groups.values()), "pagination": {"totalPages": 1}}
        elif path == "/api/user-groups" and method == "POST":
            gid = self._id()
            self.groups[gid] = {**body, "id": gid, "members": []}
            out = self.groups[gid]
        elif path.endswith("/users") and path.startswith("/api/user-groups/"):
            self.groups[path.split("/")[3]]["members"] = body["userIds"]
            out = {}
        elif path == "/api/oidc/clients" and method == "POST":
            cid = self._id()
            self.clients[cid] = {**body, "id": cid}
            out = self.clients[cid]
        elif path.endswith("/allowed-user-groups"):
            self.clients[path.split("/")[4]]["groups"] = body["userGroupIds"]
            out = {}
        elif path.endswith("/secrets"):
            out = {"secret": "s3cr3t-from-pocket-id"}
        elif path.startswith("/api/oidc/clients/") and method == "DELETE":
            self.clients.pop(path.rsplit("/", 1)[1], None)
        else:
            raise urllib.error.HTTPError(url, 404, "nope", {}, io.BytesIO(b'{"error":"not found"}'))

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R(b"" if out is None else json.dumps(out).encode())


@pytest.fixture
def env(tmp_path, monkeypatch):
    pid = FakePocketId()
    docker = {"calls": [], "containers": {}}

    def fake_docker(method, path, body=None):
        docker["calls"].append((method, path, body))
        name = fs.CONTAINER
        if method == "GET" and path == f"/containers/{name}/json":
            c = docker["containers"].get(name)
            return (200, c) if c else (404, None)
        if method == "POST" and path.startswith("/containers/create"):
            docker["containers"][name] = {
                "Config": {"Labels": body["Labels"]},
                "State": {"Running": False},
                "Spec": body,
            }
            return 201, {"Id": "x"}
        if method == "POST" and path.endswith("/start"):
            docker["containers"][name]["State"]["Running"] = True
            return 204, None
        if method == "DELETE":
            docker["containers"].pop(name, None)
            return 204, None
        return 204, None

    from backend.services import container_mutator, hw_helper_container, remote_access

    me = {**ME, "Mounts": [{**ME["Mounts"][0], "Destination": fs.DATA_DIR}]}
    monkeypatch.setattr(fs, "CONFIG_FILE", str(tmp_path / "family_signin.json"))
    monkeypatch.setattr(fs, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(fs, "_docker", fake_docker)
    monkeypatch.setattr(fs, "_self", lambda: me)
    monkeypatch.setattr(fs, "_remote", lambda: REMOTE)
    monkeypatch.setattr(fs, "_open", pid)
    monkeypatch.setattr(fs, "audit", lambda *a: None)
    monkeypatch.setattr(hw_helper_container, "host_data_dir", lambda m: "/mnt/user/appdata/kiboto")
    monkeypatch.setattr(
        container_mutator, "pull_container_image", lambda image, **k: docker["calls"].append(("PULL", image, None))
    )
    published = []
    monkeypatch.setattr(remote_access, "publish", lambda *a, **k: published.append(True))
    users = [
        {
            "id": "u1",
            "username": "gran",
            "display_name": "Gran Smith",
            "email": "gran@example.com",
            "role_id": "user",
            "status": "active",
        },
        {"id": "u2", "username": "admin", "display_name": "", "role_id": "admin", "status": "active"},
        {"id": "u3", "username": "old", "display_name": "Old", "role_id": "user", "status": "disabled"},
    ]
    from backend import users_db

    monkeypatch.setattr(users_db, "list_users", lambda *a, **k: users)
    return {"pid": pid, "docker": docker, "published": published, "users": users, "tmp": tmp_path}


def test_it_needs_https_first(env, monkeypatch):
    monkeypatch.setattr(fs, "_remote", lambda: {**REMOTE, "https": False})
    with pytest.raises(fs.SignInError, match="Passkeys need https"):
        fs.enable()
    assert fs.status()["https_ready"] is False


def test_turning_it_on_starts_a_locked_down_container_and_fills_in_the_family(env):
    st = fs.enable("admin")
    spec = env["docker"]["containers"][fs.CONTAINER]["Spec"]
    env_vars = dict(v.split("=", 1) for v in spec["Env"])
    assert env_vars["APP_URL"] == f"https://{NAME}:11411" == st["url"]
    assert len(env_vars["ENCRYPTION_KEY"]) >= 32 and len(env_vars["STATIC_API_KEY"]) >= 32
    assert env_vars["ALLOW_USER_SIGNUPS"] == "disabled"
    assert spec["Image"].startswith("ghcr.io/pocket-id/pocket-id")
    assert spec["HostConfig"]["CapDrop"] == ["ALL"] and spec["HostConfig"]["NetworkMode"] == "kiboto_default"
    assert spec["HostConfig"]["PortBindings"] == {"1411/tcp": [{"HostPort": "1411"}]}
    assert spec["HostConfig"]["Binds"] == ["/mnt/user/appdata/kiboto/pocket-id:/app/data"]
    raw = Path(fs.CONFIG_FILE).read_text()
    assert env_vars["STATIC_API_KEY"] not in raw and env_vars["ENCRYPTION_KEY"] not in raw  # kept sealed
    assert env["published"] and st["running"] and st["people"] == 2
    assert all(c[3] == env_vars["STATIC_API_KEY"] for c in env["pid"].calls)  # Kiboto calls with its key
    assert env["pid"].calls[0][1] == "/api/users"


def test_the_people_follow_kiboto(env):
    fs.enable()
    pid = env["pid"]
    names = {u["username"]: u for u in pid.users.values()}
    assert set(names) == {"gran", "admin"}  # a turned-off Kiboto user gets no account
    assert (
        names["gran"]["firstName"] == "Gran"
        and names["gran"]["lastName"] == "Smith"
        and names["gran"]["email"] == "gran@example.com"
    )
    assert names["admin"]["isAdmin"] is True and names["gran"]["isAdmin"] is False
    group = next(iter(pid.groups.values()))
    assert group["name"] == fs.GROUP and sorted(group["members"]) == sorted(u["id"] for u in names.values())
    env["users"][0]["status"] = "disabled"
    fs.sync()
    assert pid.users[names["gran"]["id"]]["disabled"] is True
    del env["users"][1]
    fs.sync()
    assert pid.users[names["admin"]["id"]]["disabled"] is True  # removed in Kiboto: turned off there
    assert fs.status()["people"] == 0


def test_a_sign_in_link(env):
    with pytest.raises(fs.SignInError, match="Turn on"):
        fs.sign_in_link("u1")
    fs.enable()
    link = fs.sign_in_link("u1")
    assert link["url"] == f"https://{NAME}:11411/lc/Tok123abc"
    assert ("POST", f"/api/users/{fs.config()['users']['u1']}/one-time-access-token") in [
        (c[0], c[1]) for c in env["pid"].calls
    ]
    assert next(c[2] for c in env["pid"].calls if c[1].endswith("one-time-access-token")) == {"ttl": 86400}
    with pytest.raises(fs.SignInError, match="isn't an active"):
        fs.sign_in_link("u3")


def test_connecting_apps(env):
    fs.enable()
    assert fs.installed_apps() == {
        "immich": f"https://{NAME}:8443/",
        "nextcloud": f"https://{NAME}:18080/",
        "jellyfin": f"http://{NAME}:8096/",
    }
    with pytest.raises(fs.SignInError, match="no sign-in preset"):
        fs.connect_app("wordpress")
    with pytest.raises(fs.SignInError, match="isn't running"):
        fs.connect_app("paperless")
    with pytest.raises(fs.SignInError, match="HTTPS address"):
        fs.connect_app("jellyfin")
    r = fs.connect_app("immich", "admin")
    client = env["pid"].clients[r["client_id"]]
    assert client["callbackURLs"] == [
        f"https://{NAME}:8443/auth/login",
        f"https://{NAME}:8443/user-settings",
        "app.immich:///oauth-callback",
    ]
    assert client["isGroupRestricted"] is True and client["groups"] == [fs.config()["group"]]
    assert r["client_secret"] == "s3cr3t-from-pocket-id" and r["issuer"] == f"https://{NAME}:11411"
    assert r["discovery"].endswith("/.well-known/openid-configuration") and "Immich" in r["where"]
    assert "s3cr3t" not in Path(fs.CONFIG_FILE).read_text()  # the secret is shown once, never kept
    again = fs.connect_app("immich")  # a new secret replaces the old client
    assert r["client_id"] not in env["pid"].clients and again["client_id"] in env["pid"].clients
    st = fs.status()
    assert {a["key"]: a["connected"] for a in st["apps"]} == {"immich": True, "nextcloud": False, "jellyfin": False}
    fs.disconnect_app("immich")
    assert env["pid"].clients == {}
    with pytest.raises(KeyError):
        fs.disconnect_app("immich")


def test_turning_off_keeps_the_data_and_on_again_reuses_the_keys(env):
    fs.enable()
    keys = (fs.config()["api_key"], fs.config()["enc_key"])
    fs.disable()
    assert fs.CONTAINER not in env["docker"]["containers"] and fs.status()["enabled"] is False
    fs.enable()
    assert (fs.config()["api_key"], fs.config()["enc_key"]) == keys
    pulls = [c for c in env["docker"]["calls"] if c[0] == "PULL"]
    fs.enable()  # nothing changed: no new container, no new download
    assert [c for c in env["docker"]["calls"] if c[0] == "PULL"] == pulls


def test_pocket_id_not_answering(env, monkeypatch):
    fs.enable()

    def down(req, timeout=10):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(fs, "_open", down)
    with pytest.raises(fs.SignInError, match="isn't answering yet"):
        fs.sync()


def test_reseal(env):
    assert fs.reseal() == 0
    fs.enable()
    assert fs.reseal() == 2


def test_the_routes(client, auth_headers, env):
    assert client.get("/api/family-signin", headers=auth_headers).json()["enabled"] is False
    assert client.post("/api/family-signin/users/u1/link", headers=auth_headers).status_code == 400
    assert client.post("/api/family-signin/apps/wordpress", headers=auth_headers).status_code == 404
    assert client.delete("/api/family-signin/apps/immich", headers=auth_headers).status_code == 404
    assert client.put("/api/family-signin", json={"enabled": True}, headers=auth_headers).json()["enabled"] is True
    assert client.post("/api/family-signin/sync", headers=auth_headers).json()["people"] == 2
    assert client.put("/api/family-signin", json={"enabled": False}, headers=auth_headers).json()["enabled"] is False


@pytest.mark.real_confirmations
def test_turning_on_and_connecting_are_confirmed(client, auth_headers, env):
    assert client.put("/api/family-signin", json={"enabled": True}, headers=auth_headers).status_code == 428
    assert client.post("/api/family-signin/apps/immich", headers=auth_headers).status_code == 428
