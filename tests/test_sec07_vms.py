"""SEC-07: VM settings can't reach host devices, the data folder, or inject QEMU options."""

import pytest
from fastapi import HTTPException

from backend.api import vms


@pytest.fixture
def roots(tmp_path, monkeypatch):
    pool = tmp_path / "pool"
    (pool / "isos").mkdir(parents=True)
    (pool / "isos" / "debian.iso").write_text("iso")
    (pool / "share").mkdir()
    (pool / "disk.qcow2").write_text("img")
    data = tmp_path / "data"
    (data / "vms" / "vm1").mkdir(parents=True)
    (data / "secret.key").write_text("k")
    monkeypatch.setattr("backend.config.ALLOWED_BROWSE_ROOTS", [str(pool)])
    monkeypatch.setattr(vms, "DATA_DIR", str(data))
    monkeypatch.setattr(vms, "VM_ISO_DIR", str(pool / "isos"))
    monkeypatch.setattr("backend.services.vm_store.DATA_DIR", str(data))
    monkeypatch.setattr("backend.services.vm_store.VM_ISO_DIR", str(pool / "isos"))
    return pool, data


def test_good_settings_pass(roots):
    pool, data = roots
    vms._validate_vm_inputs(
        secondary_disks=[{"path": str(pool / "disk.qcow2"), "bus": "virtio", "format": "qcow2"}],
        iso_path=str(pool / "isos" / "debian.iso"),
        host_shares=[{"host_path": str(pool / "share"), "mode": "ro"}],
    )
    vms._validate_vm_inputs(secondary_disks=[{"path": str(data / "vms" / "vm1" / "new.qcow2")}])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"secondary_disks": [{"path": "/dev/sda"}]},
        {"secondary_disks": [{"path": "/etc/shadow"}]},
        {"secondary_disks": [{"path": "POOL/disk.qcow2,file.locking=off"}]},
        {"secondary_disks": [{"path": "POOL/disk.qcow2", "bus": "virtio,file=/etc/shadow"}]},
        {"secondary_disks": [{"path": "POOL/disk.qcow2", "format": "qcow2,backing=x"}]},
        {"iso_path": "/dev/sdb"},
        {"iso_path": "POOL/isos/debian.iso,if=none"},
        {"host_shares": [{"host_path": "DATA"}]},
        {"host_shares": [{"host_path": "/"}]},
        {"host_shares": [{"host_path": "POOL/share", "mode": "rw,security_model=passthrough"}]},
    ],
)
def test_unsafe_settings_are_refused(roots, kwargs):
    pool, data = roots

    def fill(v):
        if isinstance(v, str):
            return v.replace("POOL", str(pool)).replace("DATA", str(data))
        if isinstance(v, list):
            return [{k: fill(x) for k, x in d.items()} for d in v]
        return v

    with pytest.raises(HTTPException) as e:
        vms._validate_vm_inputs(**{k: fill(v) for k, v in kwargs.items()})
    assert e.value.status_code == 400


def test_symlink_out_of_the_pool_is_refused(roots):
    pool, _ = roots
    (pool / "dev-link").symlink_to("/dev")
    with pytest.raises(HTTPException):
        vms._validate_vm_inputs(secondary_disks=[{"path": str(pool / "dev-link" / "sda")}])


def test_storage_admin_cannot_change_vms():
    import inspect

    src = inspect.getsource(vms)
    assert 'require_scope("system:config", "storage:admin")' not in src
    assert src.count('require_scope("vms:manage", "system:config")') >= 15
