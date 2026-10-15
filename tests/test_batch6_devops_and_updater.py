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


def test_self_updater_atomic_success():
    """Simulates a successful OTA update with rollback backup creation and cleanup."""
    mock_docker = MagicMock()

    # 1. GET inspect
    # 2. DELETE stale rollback
    # 3. POST stop target
    # 4. POST rename target to rollback
    # 5. POST create new
    # 6. POST start new
    # 7. DELETE rollback
    responses = [
        (200, {"Config": {"Env": ["A=1"]}, "HostConfig": {"Binds": []}}),  # GET inspect
        (200, {}),  # stop stale rollback
        (200, {}),  # delete stale rollback
        (200, {}),  # stop target
        (204, {}),  # rename target -> rollback
        (201, {"Id": "abc123456789"}),  # create new
        (204, {}),  # start new
        (204, {}),  # delete rollback
    ]

    with (
        patch("backend.services.self_updater._docker_request", side_effect=responses) as mock_req,
        patch("time.sleep", return_value=None),
    ):
        self_updater.apply_update_from_helper("zettnas-toolkit", "ghcr.io/fr0styx/zettnas-toolkit:latest", delay=0.0)

        # Check call sequence
        calls = [c[0] for c in mock_req.call_args_list]
        assert ("POST", "/containers/zettnas-toolkit/rename?name=zettnas-toolkit-rollback") in [
            (c[0], c[1]) for c in calls
        ]
        assert ("POST", "/containers/create?name=zettnas-toolkit") in [(c[0], c[1]) for c in calls]
        assert ("POST", "/containers/abc123456789/start") in [(c[0], c[1]) for c in calls]
        assert ("DELETE", "/containers/zettnas-toolkit-rollback?v=false") in [(c[0], c[1]) for c in calls]


def test_self_updater_creation_failure_rollback():
    """Simulates creation failure triggering automatic rollback to old container."""
    responses = [
        (200, {"Config": {}, "HostConfig": {}}),  # GET inspect
        (200, {}),  # stop stale rollback
        (200, {}),  # delete stale rollback
        (200, {}),  # stop target
        (204, {}),  # rename target -> rollback
        (500, "Image corrupt"),  # create new FAILS
        (204, {}),  # rollback rename
        (204, {}),  # rollback restart
    ]

    with (
        patch("backend.services.self_updater._docker_request", side_effect=responses) as mock_req,
        patch("time.sleep", return_value=None),
        pytest.raises(SystemExit),
    ):
        self_updater.apply_update_from_helper("zettnas-toolkit", "broken-image:latest", delay=0.0)

    calls = [(c[0][0], c[0][1]) for c in mock_req.call_args_list]
    # Rollback restoration calls must have happened
    assert ("POST", "/containers/zettnas-toolkit-rollback/rename?name=zettnas-toolkit") in calls
    assert ("POST", "/containers/zettnas-toolkit/start") in calls


def test_self_updater_start_failure_rollback():
    """Simulates startup failure triggering container deletion and automatic rollback."""
    responses = [
        (200, {"Config": {}, "HostConfig": {}}),  # GET inspect
        (200, {}),  # stop stale rollback
        (200, {}),  # delete stale rollback
        (200, {}),  # stop target
        (204, {}),  # rename target -> rollback
        (201, {"Id": "failed_cid_123"}),  # create new succeeds
        (500, "Port conflict"),  # start new FAILS
        (204, {}),  # delete failed container
        (204, {}),  # rollback rename
        (204, {}),  # rollback restart
    ]

    with (
        patch("backend.services.self_updater._docker_request", side_effect=responses) as mock_req,
        patch("time.sleep", return_value=None),
        pytest.raises(SystemExit),
    ):
        self_updater.apply_update_from_helper("zettnas-toolkit", "port-conflict:latest", delay=0.0)

    calls = [(c[0][0], c[0][1]) for c in mock_req.call_args_list]
    assert ("DELETE", "/containers/failed_cid_123?force=true") in calls
    assert ("POST", "/containers/zettnas-toolkit-rollback/rename?name=zettnas-toolkit") in calls
    assert ("POST", "/containers/zettnas-toolkit/start") in calls


def test_ci_workflow_tagging_rules():
    """Ensures GitHub Actions CI publishes :latest only on release tags, and :edge on main."""
    import re

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ci_file = os.path.join(repo_root, ".github", "workflows", "ci.yml")
    assert os.path.exists(ci_file)

    with open(ci_file, "r", encoding="utf-8") as f:
        content = f.read()

    assert "type=raw,value=edge,enable=${{ github.ref == 'refs/heads/main' }}" in content
    assert "type=raw,value=latest,enable=${{ startsWith(github.ref, 'refs/tags/v') }}" in content
