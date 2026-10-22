"""Host PCI / GPU passthrough (VFIO) for VMs."""

import os
from unittest.mock import patch

import backend.api.vms as vms
import backend.services.vm_host as vm_host


def _fake_sysfs(tmp_path, devices):
    """devices: {"0000:01:00.0": "vfio-pci" | "i915" | None}"""
    base = tmp_path / "pci"
    drivers = tmp_path / "drivers"
    base.mkdir()
    drivers.mkdir(exist_ok=True)
    for slot, driver in devices.items():
        dev = base / slot
        dev.mkdir()
        if driver:
            (drivers / driver).mkdir(exist_ok=True)
            os.symlink(drivers / driver, dev / "driver")
    return (str(base),)


def test_slot_normalization():
    assert vms._normalize_pci_slot("0000:01:00.0") == "01:00.0"
    assert vms._normalize_pci_slot("0A:1f.7") == "0a:1f.7"
    for bad in ("", None, "01:00", "01:00.8", "zz:00.0", "01:00.0,romfile=/x", "../01:00.0"):
        assert vms._normalize_pci_slot(bad) is None


def test_sanitize_drops_bad_and_duplicate_slots():
    items = [
        {"slot": "0000:01:00.0", "name": "GPU"},
        {"slot": "01:00.0", "name": "dup"},
        {"slot": "01:00.0,x-vga=on"},
        "not-a-dict",
        {"slot": "01:00.1", "name": "x" * 500},
    ]
    out = vms._sanitize_pci_list(items)
    assert [d["slot"] for d in out] == ["01:00.0", "01:00.1"]
    assert len(out[1]["name"]) == 120


def test_driver_lookup(tmp_path):
    bases = _fake_sysfs(tmp_path, {"0000:01:00.0": "vfio-pci", "0000:00:02.0": "i915", "0000:05:00.0": None})
    with patch.object(vm_host, "_PCI_SYSFS_BASES", bases):
        assert vms._pci_device_driver("01:00.0") == "vfio-pci"
        assert vms._pci_device_driver("0000:00:02.0") == "i915"
        assert vms._pci_device_driver("05:00.0") == ""
        assert vms._pci_device_driver("09:00.0") == ""


def test_problem_when_device_still_on_host_driver(tmp_path):
    bases = _fake_sysfs(tmp_path, {"0000:00:02.0": "i915"})
    vm = {"pci_passthrough": [{"slot": "00:02.0"}]}
    with patch.object(vm_host, "_PCI_SYSFS_BASES", bases):
        msg = vms._pci_passthrough_problem(vm)
    assert "00:02.0" in msg and "'i915'" in msg and "vfio-pci" in msg


def test_problem_when_vfio_node_missing(tmp_path):
    bases = _fake_sysfs(tmp_path, {"0000:01:00.0": "vfio-pci"})
    vm = {"pci_passthrough": [{"slot": "01:00.0"}]}
    with (
        patch.object(vm_host, "_PCI_SYSFS_BASES", bases),
        patch.object(vm_host, "_ensure_vfio_dev", return_value=False),
    ):
        assert "/dev/vfio" in vms._pci_passthrough_problem(vm)


def test_ready_device_has_no_problem(tmp_path):
    bases = _fake_sysfs(tmp_path, {"0000:01:00.0": "vfio-pci"})
    vm = {"pci_passthrough": [{"slot": "01:00.0"}]}
    with patch.object(vm_host, "_PCI_SYSFS_BASES", bases), patch.object(vm_host, "_ensure_vfio_dev", return_value=True):
        assert vms._pci_passthrough_problem(vm) is None
    assert vms._pci_passthrough_problem({"pci_passthrough": []}) is None


def test_create_and_update_persist_sanitized_pci_list(client, auth_headers):
    req = {
        "name": "gpu-vm",
        "os_family": "windows",
        "vcpus": 2,
        "ram_gb": 1.0,
        "disk_size_gb": 10,
        "pci_passthrough": [{"slot": "0000:01:00.0", "name": "GPU"}, {"slot": "bad"}],
    }
    res = client.post("/api/vms", json=req, headers=auth_headers)
    assert res.status_code == 200, res.text
    vm = res.json()
    assert vm["pci_passthrough"] == [{"slot": "01:00.0", "name": "GPU"}]

    res = client.put(
        f"/api/vms/{vm['id']}",
        json={"pci_passthrough": [{"slot": "01:00.1", "name": "Audio"}]},
        headers=auth_headers,
    )
    assert res.status_code == 200, res.text
    stored = next(v for v in vms._load_vms() if v["id"] == vm["id"])
    assert stored["pci_passthrough"] == [{"slot": "01:00.1", "name": "Audio"}]
    client.delete(f"/api/vms/{vm['id']}", headers=auth_headers)


def test_iommu_groups_report_driver_and_vfio(client, auth_headers):
    res = client.get("/api/vms/iommu-groups", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "vfio_available" in data
    for group in data["groups"]:
        for dev in group["devices"]:
            assert "driver" in dev and "vfio_ready" in dev
