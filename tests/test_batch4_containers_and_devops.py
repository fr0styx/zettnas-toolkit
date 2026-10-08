import os
import socket
import struct
import pytest
from unittest.mock import patch, MagicMock

from backend.services.container_mutator import check_port_available, recreate_container_ports
from backend.services.compose_synthesizer import (
    synthesize_compose_spec,
    get_container_logs_chunk,
    is_secret_key,
    mask_secret_value,
)


def test_check_port_available_range():
    """Verify port ranges below 1 or above 65535 are rejected."""
    assert not check_port_available(0)
    assert not check_port_available(70000)
    assert not check_port_available(-80)


def test_check_port_available_detects_host_proc_tcp(tmp_path):
    """Verify check_port_available inspects procfs tcp table for active listeners."""
    fake_tcp = tmp_path / "tcp"
    # Format of /proc/net/tcp:
    # sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
    # 0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345
    # 1F90 hex = 8080 dec
    fake_tcp.write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345\n"
    )

    real_exists = os.path.exists
    real_open = open

    def fake_exists(path):
        if "/proc/net/tcp" in str(path):
            return True
        return real_exists(path)

    def fake_open_fn(path, *args, **kwargs):
        if "/proc/net/tcp" in str(path):
            return real_open(fake_tcp, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    with patch("os.path.exists", side_effect=fake_exists):
        with patch("builtins.open", side_effect=fake_open_fn):
            assert not check_port_available(8080)


def test_recreate_container_ports_self_protection():
    """Verify container mutator rejects recreating zettnas-toolkit itself."""
    mock_inspect = {
        "Name": "/zettnas-toolkit",
        "Id": "c12345678901234567890",
        "Config": {"Image": "zettnas-toolkit:latest"},
        "HostConfig": {},
    }

    with patch("backend.services.container_mutator.fetch_container_raw_inspect", return_value=mock_inspect):
        with pytest.raises(ValueError, match="Cannot recreate the active ZettNAS Toolkit container"):
            recreate_container_ports("c12345678901", [{"container_port": 8082, "host_port": 8083}])


def test_synthesize_compose_spec_filters_runtime_mounts():
    """Verify Docker runtime internal mounts are excluded from synthesized Compose."""
    inspect_data = {
        "Name": "/test-app",
        "Config": {
            "Image": "nginx:alpine",
            "Env": ["MYSQL_PASSWORD=supersecret", "FOO=bar"],
        },
        "HostConfig": {
            "RestartPolicy": {"Name": "unless-stopped"},
            "PortBindings": {"80/tcp": [{"HostPort": "8080"}]},
        },
        "Mounts": [
            {"Source": "/mnt/user/appdata/nginx", "Destination": "/etc/nginx", "RW": True},
            {"Source": "/var/lib/docker/containers/123/resolv.conf", "Destination": "/etc/resolv.conf", "RW": False},
            {"Source": "/var/lib/docker/containers/123/hostname", "Destination": "/etc/hostname", "RW": False},
            {"Source": "/var/lib/docker/containers/123/hosts", "Destination": "/etc/hosts", "RW": False},
            {"Source": "shm", "Destination": "/dev/shm", "RW": True},
        ],
    }

    name, spec = synthesize_compose_spec(inspect_data, mask_secrets=True)
    assert name == "test-app"
    assert "volumes" in spec
    assert len(spec["volumes"]) == 1
    assert spec["volumes"][0] == "/mnt/user/appdata/nginx:/etc/nginx:rw"
    # Secret env variable masked
    assert "MYSQL_PASSWORD=••••••••" in spec["environment"]
    assert "FOO=bar" in spec["environment"]


def test_get_container_logs_chunk_tty_fallback():
    """Verify log parsing falls back to raw line splitting for containers with Tty: true."""
    raw_tty_log = b"2026-10-08T17:26:21.376179397Z Starting server on port 80...\n2026-10-08T17:26:22.000000000Z Ready for connections.\n"

    mock_resp = MagicMock()
    mock_resp.read.return_value = raw_tty_log
    mock_conn = MagicMock()
    mock_conn.getresponse.return_value = mock_resp

    with patch("os.path.exists", return_value=True):
        with patch("backend.services.compose_synthesizer.UnixHTTPConnection", return_value=mock_conn):
            result = get_container_logs_chunk("test-tty", tail=100)
            assert result["count"] == 2
            assert result["lines"][0]["msg"] == "Starting server on port 80..."
            assert result["lines"][1]["msg"] == "Ready for connections."


def test_ci_workflow_has_no_broken_v7_tags():
    """Verify .github/workflows/ci.yml has no non-existent @v7 tags."""
    ci_path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "ci.yml")
    with open(ci_path, "r") as f:
        content = f.read()
    assert "@v7" not in content
    assert "actions/checkout@v4" in content
    assert "actions/setup-python@v5" in content
