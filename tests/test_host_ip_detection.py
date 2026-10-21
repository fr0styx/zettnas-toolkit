"""The AI services must probe the detected host IP, never a hardcoded one."""

from unittest.mock import patch

import backend.services.ai_chat_agent as agent
import backend.services.rag_engine as rag


def test_detected_host_ip_uses_read_ip():
    with patch("backend.hardware.network.read_ip", return_value="192.0.2.10"):
        assert rag._detected_host_ip() == "192.0.2.10"


def test_detected_host_ip_ignores_loopback_and_empty():
    for value in ("127.0.0.1", "", None, "0.0.0.0"):
        with patch("backend.hardware.network.read_ip", return_value=value):
            assert rag._detected_host_ip() is None


def test_detected_host_ip_survives_errors():
    with patch("backend.hardware.network.read_ip", side_effect=OSError("boom")):
        assert rag._detected_host_ip() is None


def test_docker_host_ips_include_detected_ip_only():
    with patch.object(agent, "_detected_host_ip", return_value="192.0.2.10"):
        ips = agent._get_docker_host_ips()
    assert "192.0.2.10" in ips
    assert "10.40.30.249" not in ips


def test_ollama_host_probe_uses_detected_ip(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(rag, "_CACHED_OLLAMA_HOST", None)
    probed = []

    def fake_urlopen(req, timeout=None):
        probed.append(req.full_url)
        raise OSError("refused")

    with (
        patch.object(rag, "_detected_host_ip", return_value="192.0.2.10"),
        patch.object(rag.urllib.request, "urlopen", side_effect=fake_urlopen),
    ):
        rag._resolve_ollama_host()

    monkeypatch.setattr(rag, "_CACHED_OLLAMA_HOST", None)
    assert "http://192.0.2.10:11434/api/tags" in probed
    assert not any("10.40.30.249" in u for u in probed)
