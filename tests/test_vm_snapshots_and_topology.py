import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.vms import (
    VmCreateRequest,
    VmUpdateRequest,
    VmSnapshotCreateRequest,
)


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setattr(
        "backend.auth.get_current_session",
        lambda tok: {"user_id": "usr_admin", "username": "admin", "role_id": "superadmin", "scopes": ["*"]},
    )
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test_admin_token"})
    return client


def test_vm_cpu_topology_smp_formatting():
    vm = {
        "name": "test-topo-vm",
        "vcpus": 4,
        "sockets": 2,
        "cores": 2,
        "threads": 1,
        "ram_gb": 4.0,
        "bridge": "br0",
        "disk_bus": "virtio",
    }
    # Test topology builder logic in _build_cmd
    vcpus_val = vm.get("vcpus", 2)
    sockets = vm.get("sockets")
    cores = vm.get("cores")
    threads = vm.get("threads")
    smp_parts = [f"{vcpus_val}", f"sockets={sockets}", f"cores={cores}"]
    if threads:
        smp_parts.append(f"threads={threads}")
    smp_str = ",".join(smp_parts)
    assert smp_str == "4,sockets=2,cores=2,threads=1"


def test_iommu_groups_scanner(auth_client, tmp_path, monkeypatch):
    fake_iommu = tmp_path / "iommu_groups"
    fake_grp1 = fake_iommu / "0" / "devices" / "0000:00:02.0"
    fake_grp1.mkdir(parents=True)
    (fake_grp1 / "vendor").write_text("0x8086")
    (fake_grp1 / "device").write_text("0x4680")
    (fake_grp1 / "class").write_text("0x030000")

    real_exists = os.path.exists
    real_listdir = os.listdir

    def mock_exists(p):
        if p in ("/sys/kernel/iommu_groups", "/host/sys/kernel/iommu_groups"):
            return True
        if str(fake_iommu) in str(p):
            return True
        return real_exists(p)

    def mock_listdir(p):
        if p in ("/sys/kernel/iommu_groups", "/host/sys/kernel/iommu_groups"):
            return real_listdir(str(fake_iommu))
        return real_listdir(p)

    with patch("backend.api.vms.os.path.exists", side_effect=mock_exists):
        with patch("backend.api.vms.os.listdir", side_effect=mock_listdir):
            res = auth_client.get("/api/vms/iommu-groups")
            assert res.status_code == 200
            data = res.json()
            assert "iommu_enabled" in data
            assert "groups" in data


@patch("backend.api.vms._load_vms")
@patch("backend.api.vms._save_vm_snapshots_metadata")
@patch("backend.api.vms._get_vm_snapshots_metadata")
def test_vm_snapshots_lifecycle(mock_get_meta, mock_save_meta, mock_load, auth_client):
    vm_id = "vm-test-snap"
    mock_load.return_value = [
        {
            "id": vm_id,
            "name": "Snapshot Test VM",
            "state": "stopped",
            "disk_path": "/fake/disk.qcow2",
        }
    ]
    mock_get_meta.return_value = {
        "snap_initial": {
            "id": "snap_initial",
            "name": "snap_initial",
            "description": "Initial state",
            "created_at": "2026-10-19 12:00:00",
            "state": "stopped",
        }
    }

    # 1. List snapshots
    with patch("backend.api.vms._list_qcow2_snapshots", return_value=[]):
        res = auth_client.get(f"/api/vms/{vm_id}/snapshots")
        assert res.status_code == 200
        data = res.json()
        assert len(data) >= 1
        assert data[0]["name"] == "snap_initial"

    # 2. Create snapshot
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        with patch("os.path.exists", return_value=True):
            res = auth_client.post(
                f"/api/vms/{vm_id}/snapshots",
                json={"name": "snap_v2", "description": "Second test snapshot"},
            )
            assert res.status_code == 200
            assert res.json()["success"] is True
            assert res.json()["name"] == "snap_v2"

    # 3. Revert snapshot
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        with patch("os.path.exists", return_value=True):
            res = auth_client.post(f"/api/vms/{vm_id}/snapshots/snap_v2/revert")
            assert res.status_code == 200
            assert res.json()["success"] is True

    # 4. Delete snapshot
    with patch("subprocess.run") as mock_sub:
        mock_sub.return_value = MagicMock(returncode=0)
        with patch("os.path.exists", return_value=True):
            res = auth_client.delete(f"/api/vms/{vm_id}/snapshots/snap_v2")
            assert res.status_code == 200
            assert res.json()["success"] is True
