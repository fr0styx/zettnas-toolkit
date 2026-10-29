"""
Finding a running VM's IP address: ARP by MAC and the QEMU guest agent.

Split out of backend/api/vms.py (ARC-01); the API re-exports these names.
"""

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import DATA_DIR, HOST_PROC, POOL_PATH, VM_ISO_DIR, logger
from backend.confirmations import require_confirmation
from backend.fsutil import atomic_write_json, read_json, resolve_within
from backend.services.vm_engine import QmpEngine
from backend.settings import test_mode
from backend.state import Z_STATE, add_event


def _resolve_vm_ip_by_mac(mac: str) -> str | None:
    """Inspects host ARP tables to find guest IP address matching its MAC."""
    if test_mode():
        return f"192.168.1.{100 + (hash(mac) % 150)}" if mac else "192.168.1.100"
    clean_mac = (mac or "").lower().strip()
    if not clean_mac:
        return None
    arp_paths = ["/host/proc/net/arp", "/proc/net/arp"]
    for arp_file in arp_paths:
        if os.path.exists(arp_file):
            try:
                with open(arp_file, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                for line in lines[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[3].lower() == clean_mac:
                        ip = parts[0]
                        if ip and ip != "0.0.0.0":
                            return ip
            except Exception:
                logger.debug("backend.api.vms._resolve_vm_ip_by_mac: ignored error", exc_info=True)
    return None


VM_IP_TTL_SECS = 30.0


_VM_IP_CACHE: dict[str, tuple[str | None, float]] = {}


_VM_IP_REFRESHING: set = set()


_VM_IP_LOCK = threading.Lock()


_VM_IP_BACKGROUND = True  # tests switch this off to refresh synchronously


def _qga_socket_path(vm_id: str) -> str:
    return f"/tmp/{vm_id}-qga.sock"


def _qga_command(vm_id: str, command: str, timeout: float = 1.0) -> dict[str, Any]:
    """Runs one QEMU Guest Agent command over the VM's virtio-serial channel.

    The agent has no greeting, so a guest-sync with a random id is sent first and
    replies are skipped until that id comes back; this drops stale output left by
    an earlier, timed-out client. Returns {"error": ...} when the agent is not
    running in the guest or does not answer within `timeout`.
    """
    import random
    import socket

    sock_path = _qga_socket_path(vm_id)
    if not os.path.exists(sock_path):
        return {"error": "guest agent socket not found"}

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    buf = b""

    def read_json() -> dict[str, Any]:
        nonlocal buf
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("guest agent closed the connection")
            buf += chunk
        line, buf = buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8", errors="replace") or "{}")

    try:
        sock.connect(sock_path)
        sync_id = random.randint(1, 2**31 - 1)
        sock.sendall(json.dumps({"execute": "guest-sync", "arguments": {"id": sync_id}}).encode() + b"\n")
        while read_json().get("return") != sync_id:
            pass
        sock.sendall(json.dumps({"execute": command}).encode() + b"\n")
        return read_json()
    except (OSError, ValueError, ConnectionError) as e:
        return {"error": str(e) or e.__class__.__name__}
    finally:
        sock.close()


def _qga_guest_ipv4(vm_id: str, mac: str = "") -> str | None:
    """Guest's IPv4 address from the agent, preferring the NIC with the VM's MAC."""
    res = _qga_command(vm_id, "guest-network-get-interfaces")
    ifaces = res.get("return")
    if not isinstance(ifaces, list):
        return None
    want_mac = (mac or "").lower().strip()
    candidates: list[tuple[bool, str]] = []
    for iface in ifaces:
        if not isinstance(iface, dict) or iface.get("name") == "lo":
            continue
        same_nic = bool(want_mac) and str(iface.get("hardware-address", "")).lower() == want_mac
        for addr in iface.get("ip-addresses") or []:
            ip = str(addr.get("ip-address", ""))
            if addr.get("ip-address-type") != "ipv4" or not ip:
                continue
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            candidates.append((same_nic, ip))
    if not candidates:
        return None
    candidates.sort(key=lambda c: not c[0])
    return candidates[0][1]


def _refresh_vm_ip(vm_id: str, mac: str) -> None:
    try:
        ip = _qga_guest_ipv4(vm_id, mac) or _resolve_vm_ip_by_mac(mac)
    except Exception as e:
        logger.debug(f"[VM-{vm_id}] IP refresh failed: {e}")
        ip = None
    with _VM_IP_LOCK:
        _VM_IP_CACHE[vm_id] = (ip, time.monotonic() + VM_IP_TTL_SECS)
        _VM_IP_REFRESHING.discard(vm_id)


def _cached_vm_ip(vm: dict[str, Any]) -> str | None:
    """Last known guest IP; refreshes in the background once older than VM_IP_TTL_SECS."""
    vm_id = vm.get("id")
    if not vm_id:
        return None
    with _VM_IP_LOCK:
        entry = _VM_IP_CACHE.get(vm_id)
        start = (entry is None or entry[1] <= time.monotonic()) and vm_id not in _VM_IP_REFRESHING
        if start:
            _VM_IP_REFRESHING.add(vm_id)
    if start:
        mac = vm.get("mac") or ""
        if _VM_IP_BACKGROUND:
            threading.Thread(target=_refresh_vm_ip, args=(vm_id, mac), daemon=True, name=f"vm-ip-{vm_id}").start()
        else:
            _refresh_vm_ip(vm_id, mac)
        with _VM_IP_LOCK:
            entry = _VM_IP_CACHE.get(vm_id, entry)
    return entry[0] if entry else None


def _forget_vm_ip(vm_id: str) -> None:
    with _VM_IP_LOCK:
        _VM_IP_CACHE.pop(vm_id, None)
