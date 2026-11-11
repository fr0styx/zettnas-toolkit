"""SET-03: virtual machines are read with the virtual machine right, and a machine keeps its screen.

- Seventeen read routes accepted any account with system:view, which the family role holds: the
  list with disk paths, a picture of any machine's screen, the USB and built-in devices of the NAS.
- A machine's screen port was worked out from its place in the list. After a delete, another
  machine's screen, keyboard and mouse opened under the wrong name.
"""

import pytest

from backend.services import vm_qemu, vm_store
from backend.users_db import create_user, get_user_by_username

READS = (
    "/api/vms",
    "/api/vms/telemetry",
    "/api/vms/kvm/diagnose",
    "/api/vms/isos",
    "/api/vms/catalog",
    "/api/vms/catalog/tasks",
    "/api/vms/bridges",
    "/api/vms/usb-devices",
    "/api/vms/iommu-groups",
    "/api/vms/backups",
    "/api/vms/some-vm",
    "/api/vms/some-vm/connection-info",
    "/api/vms/some-vm/error",
    "/api/vms/some-vm/status",
    "/api/vms/some-vm/screenshot",
    "/api/vms/some-vm/snapshots",
    "/api/vms/some-vm/backups",
)


def _login(client, name, role):
    if not get_user_by_username(name):
        create_user(name, name, "GoodPass123!", role_id=role)
    res = client.post("/api/auth/login", json={"username": name, "password": "GoodPass123!"})
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.mark.parametrize("role", ["share_user", "storage_admin", "kid"])
def test_no_read_route_answers_without_the_virtual_machine_right(client, role):
    headers = _login(client, f"vm_{role}", role)
    for path in READS:
        assert client.get(path, headers=headers).status_code == 403, path


def test_the_owner_still_reads_them(client, auth_headers):
    assert client.get("/api/vms", headers=auth_headers).status_code == 200
    assert client.get("/api/vms/telemetry", headers=auth_headers).status_code == 200


@pytest.fixture
def machines(monkeypatch, tmp_path):
    monkeypatch.setattr(vm_store, "VMS_CONFIG_FILE", str(tmp_path / "vms.json"))
    monkeypatch.setattr(vm_store, "_RUNNING_QEMU_PROCS", {})
    vms = [{"id": name, "name": name} for name in ("a", "b", "c")]
    vm_qemu._save_vms(vms)
    return vms


def test_a_machine_keeps_its_screen_after_another_is_deleted(machines):
    ports = {v["id"]: vm_qemu._get_qemu_vnc_port(machines, v["id"]) for v in machines}
    assert ports == {"a": 5901, "b": 5902, "c": 5903}  # as before, and now stored
    assert [v["vnc_port"] for v in vm_qemu.read_json(vm_store.VMS_CONFIG_FILE, [])] == [5901, 5902, 5903]
    machines.pop(0)  # "a" is deleted
    assert vm_qemu._get_qemu_vnc_port(machines, "b") == 5902
    assert vm_qemu._get_qemu_vnc_port(machines, "c") == 5903


def test_a_new_machine_never_gets_a_port_another_holds(machines):
    for v in machines:
        vm_qemu._get_qemu_vnc_port(machines, v["id"])
    machines.pop(0)
    machines.append({"id": "d", "name": "d"})  # third in the list: its place would give 5903
    assert vm_qemu._get_qemu_vnc_port(machines, "d") == 5901  # the next free one
    assert len({v["vnc_port"] for v in machines}) == 3


def test_a_running_machine_keeps_the_port_it_was_started_on(machines):
    vm_store._RUNNING_QEMU_PROCS["c"] = {"pid": 1, "vnc_port": 5907}
    vm_store._RUNNING_QEMU_PROCS["a"] = {"pid": 2, "vnc_port": 5902}  # holds what b's place would give
    assert vm_qemu._get_qemu_vnc_port(machines, "c") == 5907
    assert vm_qemu._get_qemu_vnc_port(machines, "b") not in (5902, 5907)
    assert vm_qemu._get_qemu_vnc_port(machines, "nobody") == 5901
