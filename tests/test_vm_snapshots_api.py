"""VM snapshot routes (backend/api/vms.py): names are held to one rule before they reach QEMU,
running VMs go through the monitor, stopped ones through qemu-img, and the list merges both."""

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from backend.api import vms as vms_api


@pytest.fixture
def vm(tmp_path, monkeypatch):
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"QFI")
    data_dir = tmp_path / "data"
    monkeypatch.setattr(vms_api, "DATA_DIR", str(data_dir))
    rec = {"id": "vm-1", "name": "Test VM", "state": "stopped", "disk_path": str(disk)}
    monkeypatch.setattr(vms_api.vm_qemu, "_load_vms", lambda: [rec])
    monkeypatch.setattr(vms_api.vm_qemu, "_is_qemu_process_alive", lambda vm_id: rec["state"] == "running")
    monkeypatch.setattr(vms_api, "add_event", lambda *a, **k: None)
    calls = SimpleNamespace(run=[], qmp=[], qmp_reply={"return": ""}, run_error=None)

    def run(cmd, **kw):
        calls.run.append(cmd)
        if calls.run_error:
            raise calls.run_error
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def qmp(vm_id, command, args, timeout):
        calls.qmp.append(args["command-line"])
        return calls.qmp_reply

    monkeypatch.setattr(vms_api.subprocess, "run", run)
    monkeypatch.setattr(vms_api.vm_qemu, "_qmp_command", qmp)
    rec["calls"] = calls
    return rec


@pytest.mark.parametrize("name", ["-l", "a b", "x;quit", "q" * 65, "dot.name"])
def test_revert_and_delete_refuse_names_qemu_would_misread(client, auth_headers, vm, name):
    base = "/api/vms/vm-1/snapshots/"
    from urllib.parse import quote

    assert client.post(base + quote(name, safe="") + "/revert", headers=auth_headers).status_code == 400
    assert client.delete(base + quote(name, safe=""), headers=auth_headers).status_code == 400
    assert vm["calls"].run == [] and vm["calls"].qmp == []


def test_create_refuses_a_leading_dash(client, auth_headers, vm):
    r = client.post("/api/vms/vm-1/snapshots", json={"name": "-c"}, headers=auth_headers)
    assert r.status_code == 400 and vm["calls"].run == []


def test_unknown_vm(client, auth_headers, vm):
    assert client.get("/api/vms/nope/snapshots", headers=auth_headers).status_code == 404
    assert client.post("/api/vms/nope/snapshots", json={"name": "s1"}, headers=auth_headers).status_code == 404
    assert client.post("/api/vms/nope/snapshots/s1/revert", headers=auth_headers).status_code == 404
    assert client.delete("/api/vms/nope/snapshots/s1", headers=auth_headers).status_code == 404


def test_stopped_vm_uses_qemu_img_and_keeps_metadata(client, auth_headers, vm):
    calls = vm["calls"]
    r = client.post(
        "/api/vms/vm-1/snapshots", json={"name": "before_update", "description": "safe"}, headers=auth_headers
    )
    assert r.status_code == 200 and r.json()["success"] is True
    assert calls.run[-1][1:4] == ["snapshot", "-c", "before_update"]
    meta = vms_api._get_vm_snapshots_metadata("vm-1")
    assert meta["before_update"]["description"] == "safe" and meta["before_update"]["state"] == "stopped"

    assert client.post("/api/vms/vm-1/snapshots/before_update/revert", headers=auth_headers).status_code == 200
    assert calls.run[-1][1:4] == ["snapshot", "-a", "before_update"]

    assert client.delete("/api/vms/vm-1/snapshots/before_update", headers=auth_headers).status_code == 200
    assert calls.run[-1][1:4] == ["snapshot", "-d", "before_update"]
    assert "before_update" not in vms_api._get_vm_snapshots_metadata("vm-1")
    assert calls.qmp == []


def test_running_vm_uses_the_monitor(client, auth_headers, vm):
    vm["state"] = "running"
    calls = vm["calls"]
    assert client.post("/api/vms/vm-1/snapshots", json={"name": "live1"}, headers=auth_headers).status_code == 200
    assert client.post("/api/vms/vm-1/snapshots/live1/revert", headers=auth_headers).status_code == 200
    assert client.delete("/api/vms/vm-1/snapshots/live1", headers=auth_headers).status_code == 200
    assert calls.qmp == ["savevm live1", "loadvm live1", "delvm live1"]
    assert calls.run == []


def test_monitor_errors(client, auth_headers, vm):
    vm["state"] = "running"
    vm["calls"].qmp_reply = {"error": "no space"}
    r = client.post("/api/vms/vm-1/snapshots", json={"name": "s1"}, headers=auth_headers)
    assert r.status_code == 500  # the details go to the server log, not the response
    r = client.post("/api/vms/vm-1/snapshots/s1/revert", headers=auth_headers)
    assert r.status_code == 500
    assert "s1" not in vms_api._get_vm_snapshots_metadata("vm-1")  # a failed snapshot is not recorded
    # deleting a snapshot the monitor no longer knows still clears our record
    assert client.delete("/api/vms/vm-1/snapshots/s1", headers=auth_headers).status_code == 200


def test_qemu_img_errors_and_missing_disk(client, auth_headers, vm):
    vm["calls"].run_error = subprocess.CalledProcessError(1, "qemu-img", stderr="locked")
    r = client.post("/api/vms/vm-1/snapshots", json={"name": "s1"}, headers=auth_headers)
    assert r.status_code == 500
    r = client.post("/api/vms/vm-1/snapshots/s1/revert", headers=auth_headers)
    assert r.status_code == 500
    assert client.delete("/api/vms/vm-1/snapshots/s1", headers=auth_headers).status_code == 200  # a warning only

    os.remove(vm["disk_path"])
    assert client.post("/api/vms/vm-1/snapshots", json={"name": "s2"}, headers=auth_headers).status_code == 400
    assert client.post("/api/vms/vm-1/snapshots/s2/revert", headers=auth_headers).status_code == 400


QEMU_IMG_LIST = """Snapshot list:
ID        TAG               VM SIZE                DATE     VM CLOCK     ICOUNT
1         base                  0 B 2026-10-20 10:00:00 00:00:00.000          0
2         live1             512 MiB 2026-10-21 11:30:00 00:12:01.100          0
"""


def test_list_merges_qemu_and_saved_snapshots(client, auth_headers, vm, monkeypatch):
    vms_api._save_vm_snapshots_metadata(
        "vm-1",
        {
            "live1": {"description": "after setup", "created_at": "2026-10-21 11:30:00", "state": "running"},
            "gone": {"id": "gone", "created_at": "2026-10-01 09:00:00", "state": "stopped"},
        },
    )
    monkeypatch.setattr(
        vms_api,
        "_list_qcow2_snapshots",
        lambda disk: [
            {"id": "1", "tag": "base", "name": "base", "vm_size": "0 B", "date": "2026-10-20 10:00:00"},
            {"id": "2", "tag": "live1", "name": "live1", "vm_size": "512", "date": "2026-10-21 11:30:00"},
        ],
    )
    snaps = {s["name"]: s for s in client.get("/api/vms/vm-1/snapshots", headers=auth_headers).json()}
    assert set(snaps) == {"base", "live1", "gone"}
    assert snaps["live1"]["description"] == "after setup" and snaps["live1"]["state_at_snapshot"] == "running"
    assert snaps["base"]["state_at_snapshot"] == "stopped"
    assert snaps["gone"]["date"] == "2026-10-01 09:00:00"


def test_qcow2_listing_parses_qemu_img(vm, monkeypatch, tmp_path):
    fake = tmp_path / "qemu-img"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setattr(vms_api.shutil, "which", lambda n: str(fake))
    monkeypatch.setattr(vms_api.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, QEMU_IMG_LIST, ""))
    snaps = vms_api._list_qcow2_snapshots(vm["disk_path"])
    assert [s["tag"] for s in snaps] == ["base", "live1"]
    # sizes are two words in qemu-img output: they used to push the unit into the date
    assert snaps[1]["vm_size"] == "512 MiB" and snaps[1]["date"] == "2026-10-21 11:30:00"
    assert snaps[0]["vm_size"] == "0 B" and snaps[0]["date"] == "2026-10-20 10:00:00"

    def broken(*a, **k):
        raise subprocess.TimeoutExpired("qemu-img", 5)

    monkeypatch.setattr(vms_api.subprocess, "run", broken)
    assert vms_api._list_qcow2_snapshots(vm["disk_path"]) == []
    assert vms_api._list_qcow2_snapshots(str(tmp_path / "missing.qcow2")) == []


def test_corrupt_snapshot_metadata_reads_as_empty(vm):
    vms_api._save_vm_snapshots_metadata("vm-1", {"a": {}})
    path = os.path.join(vms_api.DATA_DIR, "vms", "vm-1", "snapshots.json")
    with open(path) as f:
        assert json.load(f) == {"a": {}}
    with open(path, "w") as f:
        f.write("{not json")
    assert vms_api._get_vm_snapshots_metadata("vm-1") == {}
