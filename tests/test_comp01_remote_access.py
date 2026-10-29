"""COMP-01: use ZettNAS from anywhere through Tailscale or a Headscale server, against a stand-in
`tailscale` program (no account, no network): sign-in link, MagicDNS name, HTTPS addresses for
ZettNAS and Immich, and the login server kept on every `tailscale up`."""

import json
import os
import sys

import pytest

from backend.hardware.net import tailscale, tailscale_setup
from backend.services import remote_access

NAME = "zettnas.tail1234.ts.net"

# A stand-in for the tailscale CLI: what it is asked goes to calls.log, its state to state.json.
FAKE_CLI = r"""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
state_file = os.path.join(here, "state.json")
state = json.load(open(state_file)) if os.path.exists(state_file) else {"BackendState": "NoState", "served": []}
args = sys.argv[1:]
with open(os.path.join(here, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\n")
def save():
    json.dump(state, open(state_file, "w"))
if args[:1] == ["up"]:
    server = next((a.split("=", 1)[1] for a in args if a.startswith("--login-server=")), "")
    state["login_server"] = server
    if "--authkey" in args:
        state["BackendState"] = "Running"
        save()
        sys.exit(0)
    state["BackendState"] = "NeedsLogin"
    state["AuthURL"] = server + "/register/nodekey:abc123" if server else "https://login.tailscale.com/a/abc123"
    save()
    print("\nTo authenticate, visit:\n\n\t" + state["AuthURL"] + "\n")
    sys.exit(1)  # --timeout ran out before the sign-in
if args == ["status", "--json"]:
    doc = {"BackendState": state["BackendState"], "AuthURL": state.get("AuthURL", "")}
    if state["BackendState"] == "Running":
        doc["Self"] = {"DNSName": "zettnas.tail1234.ts.net.", "TailscaleIPs": ["100.101.102.103", "fd7a:115c::3"]}
        doc["CurrentTailnet"] = {"MagicDNSEnabled": True}
        doc["CertDomains"] = None if state.get("login_server") or state.get("no_certs") else ["zettnas.tail1234.ts.net"]
    print(json.dumps(doc))
    sys.exit(0)
if args == ["serve", "status", "--json"]:
    print(json.dumps({"TCP": {str(p): {"HTTPS": True} for p in state["served"]}}) if state["served"] else "{}")
    sys.exit(0)
if args[:1] == ["serve"] and args[1:2] == ["reset"]:
    state["served"] = []
    save()
    sys.exit(0)
if args[:1] == ["serve"]:
    if state.get("serve_off"):
        print("Serve is not enabled on your tailnet.\nTo enable, visit:\n\n\thttps://login.tailscale.com/f/serve?node=abc123\n")
        sys.exit(1)
    if state.get("serve_broken"):
        print("error: listener already exists")
        sys.exit(1)
    port = int(next(a for a in args if a.startswith("--https=")).split("=", 1)[1])
    state["served"] = sorted(set(state["served"]) | {port})
    save()
    sys.exit(0)
if args == ["down"]:
    state["BackendState"] = "Stopped"
    save()
    sys.exit(0)
sys.exit(2)
"""


class Cli:
    def __init__(self, folder):
        self.folder = folder

    def calls(self):
        path = self.folder / "calls.log"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def state(self):
        return json.loads((self.folder / "state.json").read_text())

    def set(self, **fields):
        path = self.folder / "state.json"
        state = json.loads(path.read_text()) if path.exists() else {"BackendState": "NoState", "served": []}
        state.update(fields)
        path.write_text(json.dumps(state))

    def sign_in(self):
        """What the person does on the sign-in page."""
        self.set(BackendState="Running", AuthURL="")


@pytest.fixture
def cli(tmp_path, monkeypatch):
    folder = tmp_path / "bin"
    folder.mkdir()
    exe = folder / "tailscale"
    exe.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    monkeypatch.setattr(
        tailscale, "_get_tailscale_container_info", lambda: {"exists": False, "running": False, "id": ""}
    )
    monkeypatch.setattr(remote_access, "immich_port", lambda: None)
    return Cli(folder)


def test_tailscale_sign_in_then_https_for_zettnas_and_immich(cli, monkeypatch):
    assert remote_access.status()["state"] == "NoState"
    s = remote_access.connect()
    assert s["state"] == "NeedsLogin" and s["auth_url"] == "https://login.tailscale.com/a/abc123"
    assert not any(a.startswith("--login-server") for a in cli.calls()[0])
    cli.sign_in()
    s = remote_access.status()
    assert (s["state"], s["name"], s["ips"], s["magic_dns"], s["https"]) == (
        "Running",
        NAME,
        ["100.101.102.103"],
        True,
        True,
    )
    assert s["addresses"] == {"zettnas": f"http://{NAME}:8082/"}  # until HTTPS is turned on
    monkeypatch.setattr(remote_access, "immich_port", lambda: 2283)
    s = remote_access.publish(app_port=8443 + 1)
    serves = [c for c in cli.calls() if c[:2] == ["serve", "--bg"]]
    assert serves == [
        ["serve", "--bg", "--yes", "--https=443", "http://127.0.0.1:8444"],
        ["serve", "--bg", "--yes", "--https=8443", "http://127.0.0.1:2283"],
    ]
    assert s["addresses"] == {"zettnas": f"https://{NAME}/", "immich": f"https://{NAME}:8443/"}
    assert s["approval_url"] == ""
    assert tailscale.settings()["app_port"] == 8444  # remembered for the next status


def test_headscale_is_kept_on_every_sign_in_and_has_no_https(cli):
    s = remote_access.connect(login_server="https://headscale.example.com/")
    assert s["login_server"] == "https://headscale.example.com"
    assert s["auth_url"] == "https://headscale.example.com/register/nodekey:abc123"
    assert "--login-server=https://headscale.example.com" in cli.calls()[0]
    # a re-sign-in with --reset must not move the node back to Tailscale's servers
    tailscale.execute_tailscale_reauth()
    assert "--login-server=https://headscale.example.com" in cli.calls()[-1]
    cli.sign_in()
    s = remote_access.publish()
    assert s["https"] is False and s["addresses"] == {"zettnas": f"http://{NAME}:8082/"}
    assert not [c for c in cli.calls() if c[:2] == ["serve", "--bg"]]


def test_a_pre_auth_key_signs_in_without_a_browser(cli):
    s = remote_access.connect(login_server="https://hs.example.com:8443", auth_key=" tskey-abc ")
    assert s["state"] == "Running" and s["auth_url"] == ""
    assert cli.calls()[0][cli.calls()[0].index("--authkey") :][:2] == ["--authkey", "tskey-abc"]


@pytest.mark.parametrize(
    "server", ["http://hs.example.com", "https://hs.example.com/path", "hs.example.com", "https://hs example"]
)
def test_bad_login_servers_are_refused(cli, server):
    with pytest.raises(ValueError, match="Headscale"):
        remote_access.connect(login_server=server)
    assert not cli.calls()


def test_https_not_allowed_yet_gives_the_page_to_allow_it(cli):
    remote_access.connect()
    cli.sign_in()
    cli.set(serve_off=True)
    s = remote_access.publish()
    assert s["approval_url"] == "https://login.tailscale.com/f/serve?node=abc123"
    assert s["addresses"]["zettnas"].startswith("http://")


def test_a_failed_serve_is_an_error(cli):
    remote_access.connect()
    cli.sign_in()
    cli.set(serve_broken=True)
    with pytest.raises(remote_access.RemoteAccessError, match="listener already exists"):
        remote_access.publish()


def test_https_waits_for_the_tailnet_certificates(cli):
    remote_access.connect()
    cli.sign_in()
    cli.set(no_certs=True)
    s = remote_access.publish()
    assert s["https"] is False and not [c for c in cli.calls() if c[:2] == ["serve", "--bg"]]


def test_publishing_before_signing_in_is_refused(cli):
    with pytest.raises(remote_access.RemoteAccessError, match="Connect"):
        remote_access.publish()


def test_disconnect_stops_serving_and_leaves(cli):
    remote_access.connect()
    cli.sign_in()
    remote_access.publish()
    s = remote_access.disconnect()
    assert ["serve", "reset"] in cli.calls() and ["down"] in cli.calls()
    assert s["state"] == "Stopped" and s["addresses"] == {}


def test_without_tailscale_the_container_is_set_up_with_the_login_server(tmp_path, monkeypatch):
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    monkeypatch.setattr(tailscale, "installed", lambda: False)
    monkeypatch.setattr(remote_access, "status", lambda: {"state": "NeedsLogin", "auth_url": ""})
    deployed = []

    def deploy(**kw):
        deployed.append(kw)
        return {"status": "success", "auth_url": "https://hs.example.com/register/nodekey:x"}

    monkeypatch.setattr(tailscale_setup, "deploy_tailscale_container", deploy)
    s = remote_access.connect(login_server="https://hs.example.com")
    assert deployed == [{"auth_key": None, "hostname": "zettnas"}]
    assert s["auth_url"] == "https://hs.example.com/register/nodekey:x"


def test_a_failed_start_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    monkeypatch.setattr(tailscale, "installed", lambda: True)
    monkeypatch.setattr(
        tailscale_setup, "execute_tailscale_up", lambda auth_key=None: {"status": "error", "output": "no tun"}
    )
    with pytest.raises(remote_access.RemoteAccessError, match="no tun"):
        remote_access.connect()


def test_the_container_carries_the_login_server(tmp_path, monkeypatch):
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    tailscale.set_login_server("https://hs.example.com")
    calls = []

    def docker(method, path, body=None, **kw):
        calls.append((method, path, body))
        if path == "/containers/tailscale/json":
            return 404, {}
        if path.startswith("/images/"):
            return 200, {}
        if path.startswith("/containers/create"):
            return 201, {"Id": "abc123def456"}
        return 204, {}

    monkeypatch.setattr("backend.services.container_mutator._docker_request", docker)
    monkeypatch.setattr(tailscale_setup.common, "docker_sock", lambda: __file__)
    monkeypatch.setattr(tailscale_setup.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        tailscale_setup, "execute_tailscale_up", lambda **kw: {"status": "needs_login", "auth_url": "u"}
    )
    tailscale_setup.deploy_tailscale_container(hostname="zettnas", state_dir=str(tmp_path / "ts"))
    env = next(body for method, path, body in calls if path.startswith("/containers/create"))["Env"]
    assert "TS_EXTRA_ARGS=--reset --login-server=https://hs.example.com --accept-routes" in env


def test_the_sign_in_link_is_found_for_either_server(tmp_path, monkeypatch):
    monkeypatch.setattr(tailscale, "SETTINGS_FILE", str(tmp_path / "remote_access.json"))
    assert tailscale.auth_url_in("visit https://login.tailscale.com/a/xyz\n") == "https://login.tailscale.com/a/xyz"
    assert tailscale.auth_url_in("visit https://hs.example.com/register/nodekey:1") == ""
    tailscale.set_login_server("https://hs.example.com")
    assert tailscale.auth_url_in("visit https://hs.example.com/register/nodekey:1") == (
        "https://hs.example.com/register/nodekey:1"
    )
    tailscale.set_login_server("")
    assert tailscale.login_args() == []


def test_immichs_port_comes_from_its_container(monkeypatch):
    monkeypatch.setattr("backend.services.immich_photos.detect", lambda: "http://192.0.2.5:2283")
    assert remote_access.immich_port() == 2283
    monkeypatch.setattr("backend.services.immich_photos.detect", lambda: "")
    assert remote_access.immich_port() is None


def test_the_api_answers_and_refuses_bad_input(cli, client, auth_headers):
    r = client.get("/api/network/remote-access", headers=auth_headers)
    assert r.status_code == 200 and r.json()["state"] == "NoState"
    r = client.post("/api/network/remote-access/connect", json={"login_server": "ftp://x"}, headers=auth_headers)
    assert r.status_code == 400
    r = client.post("/api/network/remote-access/publish", json={}, headers=auth_headers)
    assert r.status_code == 409
    r = client.post("/api/network/remote-access/connect", json={}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["auth_url"].startswith("https://login.tailscale.com/a/")
    r = client.post("/api/network/remote-access/disconnect", headers=auth_headers)
    assert r.status_code == 200 and r.json()["state"] == "Stopped"
