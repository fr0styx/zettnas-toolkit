"""Ports & Listeners lists the NAS's sockets, not Kiboto's container's (network report B8)."""

import os

from backend.hardware.net import common, listening_ports

LISTEN = (
    "  sl  local_address rem_address   st\n"
    "   0: 00000000:{port:04X} 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 1 1\n"
)


def _tree(root, port):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "tcp"), "w") as f:
        f.write(LISTEN.format(port=port))


def test_the_hosts_table_comes_first(tmp_path, monkeypatch):
    host = tmp_path / "hostproc"
    _tree(str(host / "1" / "net"), 445)  # the NAS's Samba
    _tree(str(host / "net"), 8082)  # what /host/proc/net shows: the reader's own network
    monkeypatch.setattr(common, "HOST_PROC", str(host))
    assert listening_ports.socket_tables("tcp") == [str(host / "1" / "net" / "tcp")]
    monkeypatch.setattr("backend.hardware.docker_stats.read_docker_containers", lambda: [])
    ports = {p["port"] for p in listening_ports.get_active_listening_ports()}
    assert 445 in ports and 8082 not in ports


def test_without_the_hosts_proc_it_reads_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "HOST_PROC", str(tmp_path / "missing"))
    assert listening_ports.socket_tables("udp") == ["/proc/net/udp"]
