"""
Where ZettNAS looks for a local AI runtime (AI-05).

Prompts and file excerpts go to whatever answers on the Ollama / OpenAI ports,
so only places that are this NAS are tried:

1. OLLAMA_HOST / LLM_HOST when set (the admin's explicit choice);
2. AI containers by name on a shared Docker network (zettnas-ollama, ollama,
   zettnas-ovms, ovms);
3. this machine's own LAN address and the Docker host (docker0 172.17.0.1, or the
   container's gateway when that is a Docker bridge address);
4. 127.0.0.1.

The default gateway is never tried when it is a LAN address: on host-network
installs that is the home router, and anything listening there would receive
the conversation.
"""

import ipaddress
import os
import socket
import struct
from typing import Optional

CONTAINER_NAMES = ("zettnas-ollama", "ollama", "zettnas-ovms", "ovms")
_DOCKER_BRIDGES = ipaddress.ip_network("172.16.0.0/12")


def _default_gateway() -> str | None:
    try:
        with open("/proc/net/route") as f:
            for line in f:
                fields = line.strip().split()
                if len(fields) >= 3 and fields[1] == "00000000":
                    return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except (OSError, ValueError):
        pass
    return None


def _resolves(name: str) -> bool:
    try:
        socket.getaddrinfo(name, None)
        return True
    except OSError:
        return False


def explicit_host() -> str | None:
    env = (os.environ.get("OLLAMA_HOST") or os.environ.get("LLM_HOST") or "").strip()
    if not env:
        return None
    return env.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0] or None


def candidate_hosts(host_ip: str | None = None) -> list[str]:
    hosts: list[str] = []

    def add(h: str | None) -> None:
        if h and h not in hosts:
            hosts.append(h)

    add(explicit_host())
    for name in CONTAINER_NAMES:
        if _resolves(name):
            add(name)
    add(host_ip)
    gw = _default_gateway()
    try:
        if gw and ipaddress.ip_address(gw) in _DOCKER_BRIDGES:
            add(gw)  # a Docker bridge gateway is the host itself
    except ValueError:
        pass
    add("172.17.0.1")
    add("127.0.0.1")
    return hosts
