"""
ZettNAS Toolkit - Outbound Server-Side Request Forgery (SSRF) Guard
Provides context-aware validation for outbound HTTP/HTTPS and webhook calls.
Adheres strictly to AGENTS.md §1.4 Cryptographic Security and Homelab Architecture Invariants.
"""

import ipaddress
import socket
from typing import List, Tuple, Union
from urllib.parse import urlparse

# Cloud metadata addresses to strictly reject across all contexts
CLOUD_METADATA_IPS = {
    "169.254.169.254",  # AWS / GCP / Azure IMDS
    "100.100.100.200",  # Alibaba Cloud IMDS
    "169.254.170.2",  # AWS ECS task metadata
}


def _resolve_host_ips(hostname: str) -> List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]:
    """Resolves a hostname to a list of IP address objects."""
    ips = []
    try:
        addrinfo = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for family, _, _, _, sockaddr in addrinfo:
            ip_str = sockaddr[0]
            try:
                ips.append(ipaddress.ip_address(ip_str))
            except ValueError:
                pass
    except (socket.gaierror, socket.herror, OSError):
        pass
    return ips


def is_loopback_or_metadata(ip: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """Checks if an IP is loopback, unspecified, or cloud metadata."""
    if str(ip) in CLOUD_METADATA_IPS:
        return True
    if ip.is_loopback or ip.is_unspecified:
        return True
    if ip.is_link_local:
        return True
    return False


def validate_public_url(url: str) -> Tuple[bool, str]:
    """
    Validates outbound URLs for untrusted/public callers (e.g. AI Chat web browsing).
    Strictly blocks loopback, cloud metadata, link-local, and RFC-1918 private IPs.
    """
    if not url or not isinstance(url, str):
        return False, "URL is empty or invalid"

    try:
        parsed = urlparse(url.strip())
    except Exception as e:
        return False, f"Malformed URL: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported scheme: {parsed.scheme}"

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "URL missing hostname"

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "Loopback destination prohibited"

    # Resolve IP addresses
    resolved_ips = _resolve_host_ips(hostname)
    if not resolved_ips:
        try:
            resolved_ips = [ipaddress.ip_address(hostname)]
        except ValueError:
            return False, f"Could not resolve host: {hostname}"

    for ip in resolved_ips:
        if is_loopback_or_metadata(ip):
            return False, f"Prohibited address (loopback/metadata): {ip}"
        if ip.is_private:
            return False, f"Private network address prohibited in public context: {ip}"

    return True, ""


def validate_notification_url(url: str) -> Tuple[bool, str]:
    """
    Validates outbound URLs for Admin notifications (Apprise, webhooks, ntfy).
    Allows RFC-1918 private subnets for local homelab notifications (e.g. 192.168.x.x, Home Assistant).
    Strictly blocks loopback (127.0.0.1, ::1) and cloud metadata (169.254.169.254).
    """
    if not url or not isinstance(url, str):
        return False, "URL is empty or invalid"

    try:
        parsed = urlparse(url.strip())
    except Exception as e:
        return False, f"Malformed URL: {e}"

    # If scheme is a known apprise non-http scheme (mailto, slack, telegram, etc.), allow
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return True, ""

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return False, "URL missing hostname"

    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "Loopback destination prohibited in notification targets"

    resolved_ips = _resolve_host_ips(hostname)
    if not resolved_ips:
        try:
            resolved_ips = [ipaddress.ip_address(hostname)]
        except ValueError:
            # If DNS cannot resolve immediately at save time, allow save
            return True, ""

    for ip in resolved_ips:
        if is_loopback_or_metadata(ip):
            return False, f"Prohibited notification destination (loopback/metadata): {ip}"

    return True, ""
