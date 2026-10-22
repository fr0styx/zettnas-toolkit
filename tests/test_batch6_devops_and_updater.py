"""
Tests for Batch 6: DevOps, Image Slimming, Env Var Reconciliation & Atomic Self-Updater.
"""

import os
from unittest.mock import MagicMock, call, patch

import pytest

from backend import config
from backend.services import self_updater


def test_config_env_vars_and_aliases(monkeypatch):
    """Verifies that all documented env vars and their aliases are properly supported."""
    monkeypatch.setenv("STORAGE_POOL_PATH", "/custom/storage")
    monkeypatch.setenv("ZERO_RPM_ENABLED", "1")
    monkeypatch.setenv("ZERO_RPM_TEMP", "36")
    monkeypatch.setenv("ZERO_RPM_NVME", "52")
    monkeypatch.setenv("UPS_MODE", "nut")
    monkeypatch.setenv("NUT_NAME", "office_ups")
    monkeypatch.setenv("VM_ISO_DIR", "/mnt/custom/isos")
    monkeypatch.setenv("SFTP_PORT", "22222")
    monkeypatch.setenv("TAILSCALE_STATE_DIR", "/data/tailscale_custom")
    monkeypatch.setenv("UPDATE_CHANNEL", "edge")

    # Reload config module dynamically to verify env parsing
    import importlib

    cfg = importlib.reload(config)

    assert cfg.ZERO_RPM_ENABLED is True
    assert cfg.FAN_ZERO_RPM_DEFAULT_STOP_TEMP == 36
    assert cfg.FAN_ZERO_RPM_DEFAULT_NVME_CEILING == 52
    assert cfg.UPS_MODE == "nut"
    assert cfg.NUT_NAME == "office_ups"
    assert cfg.VM_ISO_DIR == "/mnt/custom/isos"
    assert cfg.SFTP_PORT == 22222
    assert cfg.TAILSCALE_STATE_DIR == "/data/tailscale_custom"
    assert cfg.UPDATE_CHANNEL == "edge"


# Self-updater recreate tests live in tests/test_updater_recreate.py.


def test_ci_workflow_tagging_rules():
    """CI publishes :edge on main and :beta on release tags; :latest only comes from the
    promote workflow after the 7-day soak (OPS-07, tests/test_release_soak.py)."""
    import re

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ci_file = os.path.join(repo_root, ".github", "workflows", "ci.yml")
    assert os.path.exists(ci_file)

    with open(ci_file, encoding="utf-8") as f:
        content = f.read()

    assert "type=raw,value=edge,enable=${{ github.ref == 'refs/heads/main' }}" in content
    assert "type=raw,value=beta,enable=${{ startsWith(github.ref, 'refs/tags/v') }}" in content
    assert "type=raw,value=latest" not in content
