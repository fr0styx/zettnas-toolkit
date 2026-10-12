import json
import time
from unittest.mock import MagicMock, patch
import pytest

from backend.hardware.pal_storage import (
    GenericLinuxStorageAdapter,
    PlatformCapabilityError,
)
from backend.hardware.network import (
    get_mesh_vpn_status,
    execute_tailscale_up,
    execute_tailscale_down,
)


def test_worm_snapshot_lifecycle(tmp_path):
    pool_dir = tmp_path / "tank"
    pool_dir.mkdir(parents=True, exist_ok=True)
    shares_dir = pool_dir / "@shares"
    shares_dir.mkdir(parents=True, exist_ok=True)
    subvol = shares_dir / "documents"
    subvol.mkdir(parents=True, exist_ok=True)

    adapter = GenericLinuxStorageAdapter()
    adapter._pool_path = str(pool_dir)

    def mock_run_cmd(cmd):
        import os

        if "snapshot" in cmd:
            dest = cmd[-1]
            os.makedirs(dest, exist_ok=True)
            return (0, "Create a snapshot", "")
        elif "delete" in cmd:
            dest = cmd[-1]
            if os.path.exists(dest):
                os.rmdir(dest)
            return (0, "Delete subvolume", "")
        return (0, "", "")

    adapter._run_cmd = MagicMock(side_effect=mock_run_cmd)

    # 1. Create Governance WORM snapshot
    res_gov = adapter.create_snapshot(
        pool_id="tank",
        subvol_name="documents",
        snapshot_name="snap_gov_01",
        readonly=False,  # should be forced to True by WORM
        worm_mode="governance",
        retention_days=10,
    )
    assert res_gov["status"] == "created"
    assert res_gov["readonly"] is True
    assert res_gov["worm_mode"] == "governance"
    assert res_gov["retention_until"] > time.time()

    # Verify listing reflects WORM metadata
    snaps = adapter.list_snapshots("tank")
    assert len(snaps) == 1
    assert snaps[0]["name"] == "snap_gov_01"
    assert snaps[0]["worm_mode"] == "governance"
    assert snaps[0]["is_immutable"] is True

    # 2. Deletion without break-glass must be rejected
    with pytest.raises(PlatformCapabilityError, match="Governance WORM lock active"):
        adapter.delete_snapshot("tank", "snap_gov_01", break_glass=False)

    # 3. Deletion with break-glass must succeed and log security event
    with patch("backend.users_db.log_security_event") as mock_log:
        res_del = adapter.delete_snapshot(
            "tank",
            "snap_gov_01",
            break_glass=True,
            reason="Emergency space recovery authorized by CISO",
        )
        assert res_del["status"] == "deleted"
        mock_log.assert_called_once()
        assert mock_log.call_args[1]["event_type"] == "worm_break_glass_delete"

    # 4. Create Compliance WORM snapshot
    res_comp = adapter.create_snapshot(
        pool_id="tank",
        subvol_name="documents",
        snapshot_name="snap_comp_01",
        worm_mode="compliance",
        retention_days=30,
    )
    assert res_comp["status"] == "created"
    assert res_comp["worm_mode"] == "compliance"

    # 5. Compliance deletion MUST be rejected even with break-glass
    with pytest.raises(PlatformCapabilityError, match="Compliance WORM lock active"):
        adapter.delete_snapshot(
            "tank",
            "snap_comp_01",
            break_glass=True,
            reason="Attempted override",
        )


def test_mesh_vpn_status_detection():
    # 1. Test when Tailscale and Wireguard are active
    mock_ts_json = json.dumps(
        {
            "BackendState": "Running",
            "MagicDNSSuffix": "tail12345.ts.net",
            "Self": {
                "HostName": "zettnas-appliance",
                "TailscaleIPs": ["100.80.20.10", "fd7a:115c:a1e0::1"],
            },
            "Peer": {"peer1": {}, "peer2": {}},
        }
    )

    with patch("subprocess.run") as mock_subproc:

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["tailscale", "status"]:
                return MagicMock(returncode=0, stdout=mock_ts_json, stderr="")
            elif cmd[:3] == ["wg", "show", "interfaces"]:
                return MagicMock(returncode=0, stdout="wg0 wg1\n", stderr="")
            return MagicMock(returncode=1, stdout="", stderr="")

        mock_subproc.side_effect = side_effect
        status = get_mesh_vpn_status()
        assert status["tailscale"]["installed"] is True
        assert status["tailscale"]["active"] is True
        assert status["tailscale"]["ipv4"] == "100.80.20.10"
        assert status["tailscale"]["peers_count"] == 2
        assert status["wireguard"]["installed"] is True
        assert status["wireguard"]["active"] is True
        assert status["wireguard"]["interfaces"] == ["wg0", "wg1"]


def test_tailscale_up_down_execution():
    with patch("subprocess.run") as mock_subproc:
        mock_subproc.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
        res_up = execute_tailscale_up(auth_key="tskey-auth-12345", hostname="nas-01")
        assert res_up["status"] == "success"
        call_cmd = mock_subproc.call_args[0][0]
        assert "--authkey" in call_cmd
        assert "tskey-auth-12345" in call_cmd
        assert "--hostname" in call_cmd
        assert "nas-01" in call_cmd

        res_down = execute_tailscale_down()
        assert res_down["status"] == "success"
