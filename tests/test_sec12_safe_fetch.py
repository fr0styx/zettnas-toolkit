"""SEC-12: outbound fetches check every address and every redirect hop."""

import http.server
import ipaddress
import socket
import threading

import pytest

from backend.services import safe_fetch as sf


@pytest.mark.parametrize(
    "ip,context,ok",
    [
        ("8.8.8.8", "public", True),
        ("10.0.0.5", "public", False),
        ("192.168.1.10", "public", False),
        ("100.64.1.1", "public", False),
        ("127.0.0.1", "public", False),
        ("169.254.169.254", "public", False),
        ("::ffff:127.0.0.1", "public", False),
        ("192.168.1.10", "lan", True),
        ("127.0.0.1", "lan", False),
        ("169.254.169.254", "lan", False),
    ],
)
def test_address_rules(ip, context, ok):
    assert sf._ip_allowed(ipaddress.ip_address(ip), context) is ok


def test_any_blocked_answer_fails_the_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80)),
        ],
    )
    with pytest.raises(sf.UnsafeURLError):
        sf.resolve_checked("rebind.example", 80)


def test_redirect_to_an_internal_address_is_refused(monkeypatch):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:8082/api/users")
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    real_check = sf.resolve_checked

    # Treat the test server's host as "public" so only the redirect target is judged.
    def fake_resolve(host, p, context="public"):
        if host == "public.test":
            return "127.0.0.1", socket.AF_INET
        return real_check(host, p, context)

    monkeypatch.setattr(sf, "resolve_checked", fake_resolve)
    try:
        status, _, body = sf.safe_fetch(f"http://public.test:{port}/plain")
        assert status == 200 and body == b"ok"
        with pytest.raises(sf.UnsafeURLError):
            sf.safe_fetch(f"http://public.test:{port}/start")
    finally:
        server.shutdown()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "http://user:pw@example.com/"])
def test_bad_schemes_and_credentials(url):
    with pytest.raises(sf.UnsafeURLError):
        sf.safe_fetch(url)


def test_body_size_cap(monkeypatch):
    class FakeResp:
        status = 200

        def read(self, n):
            return b"x" * n

        def getheaders(self):
            return []

        def close(self):
            pass

    monkeypatch.setattr(sf, "safe_open", lambda *a, **k: FakeResp())
    with pytest.raises(sf.UnsafeURLError):
        sf.safe_fetch("http://example.com/big", max_bytes=10)
