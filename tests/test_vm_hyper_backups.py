import json
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.app_backup import (
    create_vm_backup,
    delete_vm_backup,
    get_vm_backup_dir,
    list_vm_backups,
    restore_vm_backup,
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


@pytest.fixture
def mock_vm_env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    vms_dir = data_dir / "vms"
    vms_dir.mkdir(parents=True)

    backup_base = tmp_path / "backups"
    backup_base.mkdir(parents=True)

    test_vm_id = "vm-test-hyper-001"
    target_vm_dir = vms_dir / test_vm_id
    target_vm_dir.mkdir(parents=True)

    # Dummy disk file
    disk_file = target_vm_dir / "disk.qcow2"
    disk_file.write_bytes(b"QCOW2_TEST_IMAGE_DATA_12345")

    # Dummy transient files that should NOT be archived
    (target_vm_dir / "qemu.pid").write_text("12345")
    (target_vm_dir / "qemu.sock").write_text("dummy socket")
    (target_vm_dir / "console.log").write_text("some console logs")

    # VM config list
    vms_config = [
        {
            "id": test_vm_id,
            "name": "Production-Linux-VM",
            "vcpus": 2,
            "ram_gb": 4.0,
            "disk_path": str(disk_file),
            "vm_dir": str(target_vm_dir),
            "state": "stopped",
        }
    ]
    vms_file = data_dir / "vms.json"
    vms_file.write_text(json.dumps(vms_config, indent=2))

    app_backups_file = data_dir / "app_backups.json"
    app_backups_file.write_text("[]")

    monkeypatch.setattr("backend.services.app_backup.DATA_DIR", str(data_dir))
    monkeypatch.setattr("backend.services.app_backup.POOL_PATH", str(backup_base))
    monkeypatch.setattr("backend.services.app_backup.APP_BACKUPS_REGISTRY_FILE", str(app_backups_file))
    monkeypatch.setattr("backend.api.vms.DATA_DIR", str(data_dir))
    monkeypatch.setattr("backend.services.vm_store.VMS_CONFIG_FILE", str(vms_file))

    return {
        "data_dir": data_dir,
        "backup_base": backup_base,
        "vm_id": test_vm_id,
        "vm_dir": target_vm_dir,
        "disk_file": disk_file,
        "vms_file": vms_file,
        "vm_config": vms_config[0],
    }


def test_create_and_list_vm_backup(mock_vm_env):
    vm_id = mock_vm_env["vm_id"]

    # Create backup
    record = create_vm_backup(vm_id, reason="pre-maintenance", custom_name="Test-Archive")
    assert record is not None
    assert record["vm_id"] == vm_id
    assert record["type"] == "vm"
    assert record["reason"] == "pre-maintenance"
    assert os.path.exists(record["filepath"])

    # List backups
    all_backups = list_vm_backups()
    assert len(all_backups) >= 1
    assert any(b["id"] == record["id"] for b in all_backups)

    # Filtered listing
    vm_backups = list_vm_backups(vm_id)
    assert len(vm_backups) >= 1
    assert vm_backups[0]["id"] == record["id"]


def test_restore_and_delete_vm_backup(mock_vm_env):
    vm_id = mock_vm_env["vm_id"]
    disk_file = mock_vm_env["disk_file"]

    # 1. Create backup
    record = create_vm_backup(vm_id, reason="on-demand")
    backup_id = record["id"]

    # 2. Corrupt/Modify disk file
    disk_file.write_bytes(b"CORRUPTED_DATA")
    assert disk_file.read_bytes() == b"CORRUPTED_DATA"

    # 3. Restore backup
    res = restore_vm_backup(backup_id)
    assert res["success"] is True
    assert res["backup_id"] == backup_id

    # Verify disk file is restored to original bytes
    assert disk_file.read_bytes() == b"QCOW2_TEST_IMAGE_DATA_12345"

    # 4. Delete backup
    deleted = delete_vm_backup(backup_id)
    assert deleted is True
    assert not os.path.exists(record["filepath"])

    # Verify removed from list
    remaining = list_vm_backups(vm_id)
    assert not any(b["id"] == backup_id for b in remaining)


def test_vm_backup_api_endpoints(auth_client, mock_vm_env):
    vm_id = mock_vm_env["vm_id"]

    # POST /{vm_id}/backup
    resp = auth_client.post(f"/api/vms/{vm_id}/backup", json={"reason": "api-test", "custom_name": "API-Backup"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    backup = data["backup"]
    backup_id = backup["id"]
    assert backup["vm_id"] == vm_id

    # GET /{vm_id}/backups
    resp = auth_client.get(f"/api/vms/{vm_id}/backups")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["backups"]) >= 1

    # GET /backups
    resp = auth_client.get("/api/vms/backups")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert any(b["id"] == backup_id for b in data["backups"])

    # POST /backups/{backup_id}/restore
    resp = auth_client.post(f"/api/vms/backups/{backup_id}/restore")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["result"]["success"] is True

    # DELETE /backups/{backup_id}
    resp = auth_client.delete(f"/api/vms/backups/{backup_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["deleted"] is True

    # Check 404 for invalid VM
    resp = auth_client.post("/api/vms/non-existent-vm-xyz/backup")
    assert resp.status_code == 404

    # Check 404 for deleting non-existent backup
    resp = auth_client.delete("/api/vms/backups/non-existent-backup-id")
    assert resp.status_code == 404
