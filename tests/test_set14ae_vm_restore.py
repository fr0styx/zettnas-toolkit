"""SET-14 VMs 13: a machine backup is restored in pieces, never over a running machine."""

import io
import json
import tarfile
from unittest.mock import patch

import pytest

from backend.services import app_backup


def _archive(tmp_path, vm_id="vm-a"):
    path = tmp_path / "bk.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in [
            ("manifest.json", json.dumps({"vm_config": {"id": vm_id, "name": "alpha"}}).encode()),
            ("vm_data/disk.qcow2", b"D" * (5 * 1024 * 1024 + 7)),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return str(path)


@pytest.fixture
def restore_env(tmp_path):
    vm_dir = tmp_path / "vms" / "vm-a"
    record = {"id": "bk1", "type": "vm", "filepath": _archive(tmp_path), "vm_name": "alpha"}
    with (
        patch.object(app_backup, "get_app_backups_registry", return_value=[record]),
        patch.object(
            app_backup, "_checked_vm_restore", return_value=("vm-a", str(vm_dir), {"id": "vm-a", "name": "alpha"})
        ),
        patch.object(app_backup, "DATA_DIR", str(tmp_path)),
    ):
        yield vm_dir


def test_a_stopped_machine_gets_its_disk_back_whole(restore_env):
    with patch("backend.services.vm_qemu.is_machine_running", return_value=False):
        app_backup.restore_vm_backup("bk1")
    disk = restore_env / "disk.qcow2"
    assert disk.stat().st_size == 5 * 1024 * 1024 + 7
    assert not (restore_env / "disk.qcow2.restoring").exists()


def test_a_running_machine_is_left_alone(restore_env):
    with (
        patch("backend.services.vm_qemu.is_machine_running", return_value=True),
        pytest.raises(app_backup.VmIsRunning),
    ):
        app_backup.restore_vm_backup("bk1")
    assert not (restore_env / "disk.qcow2").exists()


@pytest.mark.real_confirmations
def test_the_route_asks_first(client, auth_headers):
    res = client.post("/api/vms/backups/bk1/restore", headers=auth_headers)
    assert res.status_code == 428
