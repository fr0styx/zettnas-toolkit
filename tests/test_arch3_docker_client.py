"""One Docker client with typed errors (ARCH-3)."""

import http.server
import json
import socketserver
import threading

import pytest

from backend.services import docker_client as dc


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def address_string(self):
        return "docker"

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/containers/missing"):
            self._send(404, {"message": "No such container: missing"})
        elif self.path.startswith("/containers/busy"):
            self._send(409, {"message": "container is already running"})
        else:
            self._send(200, {"path": self.path})


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


@pytest.fixture
def docker(tmp_path, monkeypatch):
    sock = str(tmp_path / "docker.sock")
    server = _Server(sock, _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(dc, "docker_sock", lambda: sock)
    yield
    server.shutdown()
    server.server_close()


def test_request_and_call(docker):
    status, data = dc.request("GET", '/containers/json?filters={"status":["running"]}')
    assert status == 200 and data["path"].startswith("/containers/json?filters=")
    assert dc.call("GET", "/version")["path"] == "/version"


def test_typed_errors(docker):
    with pytest.raises(dc.DockerNotFound) as e:
        dc.call("GET", "/containers/missing/json")
    assert e.value.status == 404 and "No such container" in e.value.message
    with pytest.raises(dc.DockerConflict):
        dc.call("GET", "/containers/busy/json")
    assert dc.request("GET", "/containers/missing/json")[0] == 404  # request() never raises for HTTP errors


def test_missing_socket_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, "docker_sock", lambda: str(tmp_path / "none.sock"))
    with pytest.raises(dc.DockerUnavailable):
        dc.call("GET", "/version")


def test_one_connection_class():
    from backend.hardware import docker_stats
    from backend.services import container_mutator, docker_diagnostics

    assert docker_stats.UnixHTTPConnection is dc.UnixHTTPConnection
    assert docker_diagnostics.UnixHTTPConnection is dc.UnixHTTPConnection
    assert container_mutator.UnixHTTPConnection is dc.UnixHTTPConnection
