"""SET-02: the first "Connect" on a NAS without Tailscale passes Kiboto's own Docker guard, after a
question on the server.

The Tailscale container runs on the host's network. Kiboto's guard refuses such a container unless
the request says a person agreed; the Tailscale set-up never said so, so "Connect" and the 1-click
deploy were refused on every install that had no Tailscale yet.
"""

from unittest.mock import patch

import pytest

from backend import docker_proxy
from backend.hardware.net import tailscale, tailscale_setup


def test_the_container_request_says_a_person_agreed(tmp_path):
    sent = []

    def docker(method, path, body=None, headers=None):
        sent.append((method, path, body, headers))
        if path == "/containers/tailscale/json":
            return 404, {}
        if "/containers/create" in path:
            return 201, {"Id": "112233445566778899"}
        return (204, {}) if "/start" in path else (200, {})

    with (
        patch("os.path.exists", return_value=True),
        patch("time.sleep", return_value=None),
        patch("backend.services.container_mutator._docker_request", side_effect=docker),
        patch("backend.hardware.net.tailscale_setup.execute_tailscale_up", return_value={"status": "needs_login"}),
    ):
        res = tailscale_setup.deploy_tailscale_container(state_dir=str(tmp_path / "tailscale"))
    assert res["status"] == "success"
    create = next(c for c in sent if "/containers/create" in c[1])
    assert create[3] == {"X-Kiboto-Elevated": "1"}
    # and that is what the guard needs for a container on the host's network
    assert "NetworkMode=host" in docker_proxy.elevated_reasons("/containers/create", create[2])


@pytest.mark.real_confirmations
def test_connect_asks_first_when_tailscale_is_not_here(client, auth_headers, monkeypatch):
    ran = []
    monkeypatch.setattr(tailscale, "installed", lambda: False)
    monkeypatch.setattr("backend.services.remote_access.connect", lambda *a: ran.append(a) or {"state": "NeedsLogin"})
    asked = client.post("/api/network/remote-access/connect", json={}, headers=auth_headers)
    assert asked.status_code == 428 and asked.json()["action"] == "network.tailscale_install"
    assert ran == []
    deploy = client.post("/api/network/mesh-vpn/tailscale/deploy", json={}, headers=auth_headers)
    assert deploy.status_code == 428 and deploy.json()["action"] == "network.tailscale_install"


@pytest.mark.real_confirmations
def test_connect_does_not_ask_when_tailscale_is_already_here(client, auth_headers, monkeypatch):
    monkeypatch.setattr(tailscale, "installed", lambda: True)
    monkeypatch.setattr("backend.services.remote_access.connect", lambda *a: {"state": "Running"})
    res = client.post("/api/network/remote-access/connect", json={}, headers=auth_headers)
    assert res.status_code == 200 and res.json()["state"] == "Running"
