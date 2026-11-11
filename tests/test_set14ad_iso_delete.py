"""SET-14 VMs 13: an installer image in the default folder (where downloads and uploads go) can be deleted."""

import os
from unittest.mock import patch

from backend.services import vm_host


def test_the_default_folder_is_in_the_list(tmp_path):
    with patch.object(vm_host, "VM_ISO_DIR", str(tmp_path / "vms" / "isos")):
        assert str(tmp_path / "vms" / "isos") in vm_host.iso_dirs()


def test_delete_in_the_default_folder(client, auth_headers, tmp_path):
    iso_dir = tmp_path / "vms" / "isos"
    iso_dir.mkdir(parents=True)
    f = iso_dir / "debian.iso"
    f.write_bytes(b"x")
    with patch.object(vm_host, "VM_ISO_DIR", str(iso_dir)):
        res = client.delete(f"/api/vms/isos?path={f}", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert not os.path.exists(f)


def test_outside_the_folders_is_refused(client, auth_headers, tmp_path):
    f = tmp_path / "elsewhere.iso"
    f.write_bytes(b"x")
    res = client.delete(f"/api/vms/isos?path={f}", headers=auth_headers)
    assert res.status_code == 400
    assert f.exists()
