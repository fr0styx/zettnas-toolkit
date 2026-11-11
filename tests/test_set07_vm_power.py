"""SET-07: "Shut down" asks the machine and never ends it; the list is written field by field;
choices that damaged a machine are closed."""

import json
import os
import time

import pytest

from backend.api import vms as vms_api
from backend.services import vm_qemu, vm_store


@pytest.fixture
def machines(tmp_path, monkeypatch):
    path = tmp_path / "vms.json"
    monkeypatch.setattr(vm_store, "VMS_CONFIG_FILE", str(path))
    monkeypatch.setattr(vms_api, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(vms_api, "add_event", lambda *a, **k: None)
    state = {"alive": {"vm-a"}, "qmp": [], "reply": {"return": {}}, "killed": []}
    monkeypatch.setattr(vm_qemu, "_is_qemu_process_alive", lambda vm_id: vm_id in state["alive"])
    monkeypatch.setattr(vm_qemu, "_qmp_command", lambda vm_id, cmd, *a, **k: state["qmp"].append(cmd) or state["reply"])
    monkeypatch.setattr(vm_qemu, "_sync_cleanup_qemu_process", lambda vm_id, force=False: state["killed"].append(vm_id))
    monkeypatch.setattr(vm_qemu, "_forget_process", lambda vm_id: None)

    def write(*vms):
        path.write_text(json.dumps(list(vms)))

    def read():
        return {v["id"]: v for v in json.loads(path.read_text())}

    write({"id": "vm-a", "name": "alpha", "state": "running"}, {"id": "vm-b", "name": "beta", "state": "stopped"})
    state.update(write=write, read=read)
    return state


def test_shut_down_presses_the_power_button_and_ends_nothing(client, auth_headers, machines):
    r = client.post("/api/vms/vm-a/action", json={"action": "stop"}, headers=auth_headers)
    assert r.status_code == 200 and r.json()["state"] == "shutting_down"
    assert machines["qmp"] == ["system_powerdown"]
    assert machines["killed"] == []
    saved = machines["read"]()["vm-a"]
    assert saved["state"] == "shutting_down" and saved["shutdown_asked_at"] <= time.time()


def test_a_machine_that_is_off_within_a_moment_is_stopped(client, auth_headers, machines, monkeypatch):
    def powerdown(vm_id, cmd, *a, **k):
        machines["alive"].discard(vm_id)
        return {"return": {}}

    monkeypatch.setattr(vm_qemu, "_qmp_command", powerdown)
    r = client.post("/api/vms/vm-a/action", json={"action": "acpi_shutdown"}, headers=auth_headers)
    assert r.json()["state"] == "stopped" and machines["killed"] == []


def test_a_request_the_machine_does_not_take_is_said_and_ends_nothing(client, auth_headers, machines):
    machines["reply"] = {"error": "QMP connect failed"}
    r = client.post("/api/vms/vm-a/action", json={"action": "stop"}, headers=auth_headers)
    assert r.status_code == 409 and "Turn off now" in r.json()["detail"]
    assert machines["killed"] == []
    assert machines["read"]()["vm-a"]["state"] == "running"


def test_only_turn_off_now_ends_the_machine(client, auth_headers, machines):
    r = client.post("/api/vms/vm-a/action", json={"action": "force_off"}, headers=auth_headers)
    assert r.json()["state"] == "stopped" and machines["killed"] == ["vm-a"]


def test_the_list_says_when_turn_off_now_is_offered(machines, monkeypatch):
    machines["write"]({"id": "vm-a", "name": "alpha", "state": "shutting_down", "shutdown_asked_at": time.time() - 30})
    vm = vm_qemu._load_vms()[0]
    assert vm["turn_off_offered"] is False and 29 <= vm["shutdown_waited_seconds"] <= 32
    machines["write"]({"id": "vm-a", "name": "alpha", "state": "shutting_down", "shutdown_asked_at": time.time() - 121})
    assert vm_qemu._load_vms()[0]["turn_off_offered"] is True
    machines["alive"].clear()  # the system inside finished
    vm = vm_qemu._load_vms()[0]
    assert vm["state"] == "stopped" and "turn_off_offered" not in vm and "shutdown_asked_at" not in vm


def test_start_on_a_paused_machine_resumes_it(client, auth_headers, machines, monkeypatch):
    machines["write"]({"id": "vm-a", "name": "alpha", "state": "paused"})
    monkeypatch.setattr(vm_qemu, "_start_qemu", lambda *a, **k: pytest.fail("a frozen machine is not started again"))
    r = client.post("/api/vms/vm-a/action", json={"action": "start"}, headers=auth_headers)
    assert r.json()["state"] == "running" and machines["qmp"] == ["cont"]


@pytest.mark.real_confirmations
def test_a_paused_machine_is_not_deleted(client, auth_headers, machines):
    machines["write"]({"id": "vm-a", "name": "alpha", "state": "paused"})
    r = client.request("DELETE", "/api/vms/vm-a", headers={**auth_headers, "X-Confirmed": "true"})
    assert r.status_code in (400, 428)
    assert "vm-a" in machines["read"]()


def test_an_action_writes_its_own_fields_into_the_list_as_it_is_now(client, auth_headers, machines, monkeypatch):
    """A start takes seconds. What changed meanwhile was written over with the copy from before."""
    machines["alive"].clear()
    machines["write"](
        {"id": "vm-a", "name": "alpha", "state": "stopped"}, {"id": "vm-b", "name": "beta", "state": "stopped"}
    )

    def slow_start(target_vm, vnc_port):
        vm_qemu.save_fields("vm-b", {"description": "edited meanwhile"})
        vm_qemu.save_fields("vm-a", {"description": "also edited"})
        machines["alive"].add("vm-a")
        target_vm["network_mode"] = "slirp"
        return True, None

    monkeypatch.setattr(vm_qemu, "_start_qemu", slow_start)
    r = client.post("/api/vms/vm-a/action", json={"action": "start"}, headers=auth_headers)
    assert r.status_code == 200
    now = machines["read"]()
    assert now["vm-b"]["description"] == "edited meanwhile"
    assert now["vm-a"]["description"] == "also edited"
    assert now["vm-a"]["state"] == "running" and now["vm-a"]["network_mode"] == "slirp"


def test_read_only_is_read_under_both_names():
    assert vm_qemu.share_is_read_only({"mode": "ro"})
    assert vm_qemu.share_is_read_only({"readonly": True})  # what the edit form saves
    assert not vm_qemu.share_is_read_only({"mode": "rw"})
    assert not vm_qemu.share_is_read_only({"readonly": False})
    assert not vm_qemu.share_is_read_only({})


def test_an_extra_disk_never_gets_the_system_disks_file():
    assert vm_qemu.extra_disk_path("/d", {"name": "disk"}, 0) == "/d/extra_disk_1.qcow2"
    assert vm_qemu.extra_disk_path("/d", {}, 1) == "/d/extra_disk_2.qcow2"
    assert vm_qemu.extra_disk_path("/d", {"name": "media"}, 0) == "/d/media.qcow2"
    assert vm_qemu.extra_disk_path("/d", {"name": "../x"}, 0) == "/d/x.qcow2"


def test_a_new_name_follows_the_rule_and_none_removes_the_installer_image(client, auth_headers, machines):
    machines["alive"].clear()
    machines["write"]({"id": "vm-a", "name": "alpha", "state": "stopped", "iso_path": "/mnt/user/isos/a.iso"})
    from fastapi import HTTPException

    def update(**fields):  # the function itself: the route's answer wants a complete machine
        return vms_api.update_vm("vm-a", vms_api.VmUpdateRequest(**fields), principal=None)

    for bad in ("my pc", "a,b", "a/b", "x"):
        with pytest.raises(HTTPException) as refused:
            update(name=bad)
        assert refused.value.status_code == 400, bad
    update(name="alpha-2")
    assert machines["read"]()["vm-a"]["name"] == "alpha-2"
    assert machines["read"]()["vm-a"]["iso_path"] == "/mnt/user/isos/a.iso"  # not sent: no change
    update(iso_path=None)
    assert machines["read"]()["vm-a"]["iso_path"] is None


def test_the_connection_details_name_no_port_of_the_nas(client, auth_headers, machines):
    body = client.get("/api/vms/vm-a/connection-info", headers=auth_headers).json()
    assert "ssh_port" not in body and body["ssh_command"] == ""
