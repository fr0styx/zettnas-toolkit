"""
One way to fetch a URL that a user, a feed or the AI supplied (SEC-12).

validate_public_url() checked the hostname once, then urllib resolved it again
and followed redirects on its own, so a redirect to http://127.0.0.1:8082 or a
DNS answer that changed between the two lookups (rebinding) reached internal
services. safe_open()/safe_fetch():

- resolve the host once, check every address, and connect to that exact
  address (TLS still verifies the original hostname);
- follow redirects themselves, re-checking each hop (max 5);
- cap the body size for safe_fetch().

context "public": internet only (no private, loopback, link-local, CGNAT,
multicast or reserved ranges). context "lan": also LAN addresses (for
self-hosted catalog sources); never loopback, link-local or cloud metadata.
"""

import http.client
import ipaddress
import socket
import ssl
from typing import Optional, Union
from urllib.parse import urljoin, urlsplit

IP = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]  # noqa: UP007
_METADATA = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("100.100.100.200"),
    ipaddress.ip_address("169.254.170.2"),
}
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    pass


def _ip_allowed(ip: IP, context: str) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip in _METADATA or ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return False
    if context == "lan":
        return not ip.is_reserved or ip.is_private
    if ip.is_private or ip.is_reserved or (isinstance(ip, ipaddress.IPv4Address) and ip in _CGNAT):
        return False
    return ip.is_global


def resolve_checked(host: str, port: int, context: str = "public") -> tuple[str, int]:
    """First address of `host` that passes the checks; raises if any address fails."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise UnsafeURLError(f"Could not resolve {host}") from e
    addrs = []
    for family, _, _, _, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if not _ip_allowed(ip, context):
            raise UnsafeURLError(f"{host} resolves to a blocked address ({ip})")
        addrs.append((family, sockaddr[0]))
    if not addrs:
        raise UnsafeURLError(f"Could not resolve {host}")
    return addrs[0][1], addrs[0][0]


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, port, pinned_ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = pinned_ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, pinned_ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def safe_open(
    url: str,
    context: str = "public",
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> http.client.HTTPResponse:
    """Opens `url` after checking every hop. Caller reads and closes the response."""
    current = url.strip()
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https") or not parts.hostname:
            raise UnsafeURLError(f"Unsupported URL: {current[:120]}")
        if parts.username or parts.password:
            raise UnsafeURLError("URLs with credentials are not allowed")
        port = parts.port or (443 if scheme == "https" else 80)
        ip, _family = resolve_checked(parts.hostname, port, context)
        cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
        conn = cls(parts.hostname, port, ip, timeout)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        conn.request(method, path, headers={"User-Agent": "ZettNAS-Toolkit", **(headers or {})})
        resp = conn.getresponse()
        if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
            location = urljoin(current, resp.getheader("Location"))
            resp.close()
            conn.close()
            current = location
            if resp.status == 303:
                method = "GET"
            continue
        resp.url = current  # type: ignore[attr-defined]
        return resp
    raise UnsafeURLError("Too many redirects")


def safe_fetch(
    url: str,
    context: str = "public",
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
    max_bytes: int = 5 * 1024 * 1024,
) -> tuple[int, dict[str, str], bytes]:
    """GET with the checks above; returns (status, headers, body up to max_bytes)."""
    resp = safe_open(url, context=context, headers=headers, timeout=timeout)
    try:
        body = resp.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise UnsafeURLError(f"Response larger than {max_bytes} bytes")
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body
    finally:
        resp.close()
