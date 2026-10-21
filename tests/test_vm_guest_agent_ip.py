"""VM guest IP discovery through the QEMU Guest Agent, with ARP fallback."""

import json
import os
import socket
import tempfile
import threading
from unittest.mock import patch

import pytest

import backend.api.vms as vms

IFACES = [
    {"name": "lo", "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "127.0.0.1"}]},
    {
        "name": "docker0",
        "hardware-address": "02:42:ac:11:00:01",
        "ip-addresses": [{"ip-address-type": "ipv4", "ip-address": "172.17.0.1"}],
    },
    {
        "name": "eth0",
        "hardware-address": "52:54:00:aa:bb:cc",
        "ip-addresses": [
            {"ip-address-type": "ipv6", "ip-address": "fe80::1"},
            {"ip-address-type": "ipv4", "ip-address": "169.254.3.4"},
            {"ip-address-type": "ipv4", "ip-address": "192.0.2.50"},
        ],
    },
]


class FakeAgent:
    """Minimal qemu-guest-agent speaking newline-delimited JSON on a UNIX socket."""

    def __init__(self, path, ifaces, stale_line=None):
        self.path = path
        self.ifaces = ifaces
        self.stale_line = stale_line
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.srv.accept()
        with conn:
            f = conn.makefile("rwb")
            if self.stale_line:
                f.write(self.stale_line + b"\n")
                f.flush()
            for raw in f:
                req = json.loads(raw)
                if req["execute"] == "guest-sync":
                    resp = {"return": req["arguments"]["id"]}
                elif req["execute"] == "guest-network-get-interfaces":
                    resp = {"return": self.ifaces}
                else:
                    resp = {"error": {"class": "CommandNotFound"}}
                f.write(json.dumps(resp).encode() + b"\n")
                f.flush()

    def close(self):
        self.srv.close()


@pytest.fixture
def agent_dir(monkeypatch):
    # AF_UNIX paths must stay short, so use a short temp dir.
    d = tempfile.mkdtemp(prefix="qga")
    monkeypatch.setattr(vms, "_qga_socket_path", lambda vm_id: os.path.join(d, f"{vm_id}.sock"))
    yield d


def test_agent_ip_prefers_vm_nic_and_skips_loopback_and_link_local(agent_dir):
    agent = FakeAgent(os.path.join(agent_dir, "vm1.sock"), IFACES)
    try:
        assert vms._qga_guest_ipv4("vm1", "52:54:00:AA:BB:CC") == "192.0.2.50"
    finally:
        agent.close()


def test_agent_skips_stale_output_before_sync(agent_dir):
    stale = json.dumps({"return": {"leftover": True}}).encode()
    agent = FakeAgent(os.path.join(agent_dir, "vm1.sock"), IFACES, stale_line=stale)
    try:
        assert vms._qga_guest_ipv4("vm1", "52:54:00:aa:bb:cc") == "192.0.2.50"
    finally:
        agent.close()


def test_agent_without_mac_match_uses_first_usable_ipv4(agent_dir):
    agent = FakeAgent(os.path.join(agent_dir, "vm1.sock"), IFACES)
    try:
        assert vms._qga_guest_ipv4("vm1", "") == "172.17.0.1"
    finally:
        agent.close()


def test_missing_agent_socket_returns_error(agent_dir):
    assert "error" in vms._qga_command("nope", "guest-ping")
    assert vms._qga_guest_ipv4("nope") is None


def test_silent_agent_times_out(agent_dir):
    path = os.path.join(agent_dir, "vm1.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)
    try:
        res = vms._qga_command("vm1", "guest-ping", timeout=0.2)
        assert "error" in res
    finally:
        srv.close()


def test_cached_ip_prefers_agent_then_arp(monkeypatch):
    monkeypatch.setattr(vms, "_VM_IP_BACKGROUND", False)
    vms._forget_vm_ip("vmA")
    vm = {"id": "vmA", "mac": "52:54:00:aa:bb:cc", "state": "running"}
    with (
        patch.object(vms, "_qga_guest_ipv4", return_value="192.0.2.50"),
        patch.object(vms, "_resolve_vm_ip_by_mac", return_value="192.0.2.99"),
    ):
        assert vms._cached_vm_ip(vm) == "192.0.2.50"

    vms._forget_vm_ip("vmA")
    with (
        patch.object(vms, "_qga_guest_ipv4", return_value=None),
        patch.object(vms, "_resolve_vm_ip_by_mac", return_value="192.0.2.99"),
    ):
        assert vms._cached_vm_ip(vm) == "192.0.2.99"
    vms._forget_vm_ip("vmA")


def test_cached_ip_is_reused_until_ttl(monkeypatch):
    monkeypatch.setattr(vms, "_VM_IP_BACKGROUND", False)
    vms._forget_vm_ip("vmB")
    vm = {"id": "vmB", "mac": "", "state": "running"}
    calls = []

    def agent(vm_id, mac):
        calls.append(vm_id)
        return "192.0.2.7"

    with patch.object(vms, "_qga_guest_ipv4", side_effect=agent):
        assert vms._cached_vm_ip(vm) == "192.0.2.7"
        assert vms._cached_vm_ip(vm) == "192.0.2.7"
    assert calls == ["vmB"]
    vms._forget_vm_ip("vmB")


def test_list_vms_overlays_live_ip_for_running_vms(monkeypatch):
    monkeypatch.setattr(vms, "_VM_IP_BACKGROUND", False)
    stored = [
        {"id": "r1", "state": "running", "mac": "m1", "ip_address": ""},
        {"id": "s1", "state": "stopped", "mac": "m2", "ip_address": "10.0.0.9"},
    ]
    for v in stored:
        vms._forget_vm_ip(v["id"])
    with (
        patch.object(vms, "_load_vms", return_value=[dict(v) for v in stored]),
        patch.object(vms, "_qga_guest_ipv4", return_value="192.0.2.21"),
    ):
        out = vms.list_vms()
    assert out[0]["ip_address"] == "192.0.2.21"
    assert out[1]["ip_address"] == "10.0.0.9"
    for v in stored:
        vms._forget_vm_ip(v["id"])
