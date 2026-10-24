"""VM console tickets (single use, per VM, expiring; sessions and tokens need a console scope)
and disk resizing (grow only, primary or secondary disk, live VMs told through the monitor)."""

import subprocess
import time

import pytest

from backend.api import vms as vms_api

# ---------------------------------------------------------------------------
# Console tickets
# ---------------------------------------------------------------------------


@pytest.fixture
def no_sessions(monkeypatch):
    """No session, API token or stream ticket matches unless a test says so."""
    import backend.api.auth as auth_api
    import backend.auth as auth_mod
    import backend.users_db as users_db

    monkeypatch.setattr(auth_mod, "get_current_session", lambda tok: None)
    monkeypatch.setattr(users_db, "validate_user_session", lambda tok: None)
    monkeypatch.setattr(users_db, "validate_scoped_api_token", lambda tok: None)
    monkeypatch.setattr(auth_api, "validate_and_consume_stream_ticket", lambda tok: None)
    vms_api._CONSOLE_TICKETS.clear()
    yield
    vms_api._CONSOLE_TICKETS.clear()


def test_console_ticket_is_single_use_and_bound_to_its_vm(no_sessions):
    vms_api._CONSOLE_TICKETS["t1"] = {"vm_id": "vm-a", "expires_at": time.time() + 60}
    vms_api._CONSOLE_TICKETS["t2"] = {"vm_id": "vm-a", "expires_at": time.time() + 60}
    assert vms_api._validate_console_ticket("t1", "vm-a") is True
    assert vms_api._validate_console_ticket("t1", "vm-a") is False  # used up
    assert vms_api._validate_console_ticket("t2", "vm-b") is False  # another VM's ticket
    assert vms_api._validate_console_ticket("", "vm-a") is False
    assert vms_api._validate_console_ticket(None, "vm-a") is False


def test_expired_console_tickets_are_pruned(no_sessions):
    vms_api._CONSOLE_TICKETS["old"] = {"vm_id": "vm-a", "expires_at": time.time() - 1}
    vms_api._CONSOLE_TICKETS["other"] = {"vm_id": "vm-b", "expires_at": time.time() - 5}
    assert vms_api._validate_console_ticket("old", "vm-a") is False
    assert vms_api._CONSOLE_TICKETS == {}


@pytest.mark.parametrize(
    ("scopes", "ok"),
    [
        (["vms:console"], True),
        (["*"], True),
        (["system:config"], True),
        (["vms:read", "storage:read"], False),
        ([], False),
    ],
)
def test_sessions_need_a_console_scope(no_sessions, monkeypatch, scopes, ok):
    import backend.auth as auth_mod

    monkeypatch.setattr(
        auth_mod,
        "get_current_session",
        lambda tok: (
            {"user_id": "u1", "username": "u", "role_id": "custom", "scopes": scopes} if tok == "sess" else None
        ),
    )
    assert vms_api._validate_console_ticket("sess", "vm-a") is ok


def test_api_tokens_and_stream_tickets(no_sessions, monkeypatch):
    import backend.api.auth as auth_api
    import backend.users_db as users_db

    monkeypatch.setattr(
        users_db,
        "validate_scoped_api_token",
        lambda tok: (
            {"user_id": "u2", "username": "bot", "role_id": "api", "scopes": ["vms:manage"]} if tok == "tok" else None
        ),
    )
    assert vms_api._validate_console_ticket("tok", "vm-a") is True
    monkeypatch.setattr(
        auth_api,
        "validate_and_consume_stream_ticket",
        lambda tok: {"user_id": "u3", "username": "viewer", "role_id": "custom", "scopes": ["vms:read"]},
    )
    assert vms_api._validate_console_ticket("stream", "vm-a") is False  # a stream ticket without a console scope


def test_a_failing_session_lookup_does_not_let_anyone_in(no_sessions, monkeypatch):
    import backend.auth as auth_mod

    def boom(tok):
        raise RuntimeError("db locked")

    monkeypatch.setattr(auth_mod, "get_current_session", boom)
    assert vms_api._validate_console_ticket("sess", "vm-a") is False


# ---------------------------------------------------------------------------
# Disk resize
# ---------------------------------------------------------------------------


@pytest.fixture
def vm(tmp_path, monkeypatch):
    disk = tmp_path / "disk.qcow2"
    disk.write_bytes(b"QFI")
    rec = {
        "id": "vm-1",
        "name": "Test VM",
        "disk_path": str(disk),
        "disk_size_gb": 32,
        "secondary_disks": [{"name": "data", "path": str(tmp_path / "data.img"), "size_gb": 20}],
    }
    saved = []
    monkeypatch.setattr(vms_api, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(vms_api.vm_qemu, "_load_vms", lambda: [rec])
    monkeypatch.setattr(vms_api.vm_qemu, "_save_vms", lambda v: saved.append([dict(x) for x in v]))
    monkeypatch.setattr(vms_api.vm_qemu, "_is_qemu_process_alive", lambda vm_id: rec.get("running", False))
    monkeypatch.setattr(vms_api, "add_event", lambda *a, **k: None)
    fake_qemu_img = tmp_path / "qemu-img"
    fake_qemu_img.write_text("#!/bin/sh\n")
    monkeypatch.setattr(vms_api.shutil, "which", lambda n: str(fake_qemu_img))
    runs, qmp = [], []

    def run(cmd, **kw):
        runs.append(cmd)
        if rec.get("fail"):
            raise subprocess.CalledProcessError(1, cmd, stderr="image is locked")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(vms_api.subprocess, "run", run)
    monkeypatch.setattr(vms_api.vm_qemu, "_qmp_command", lambda vm_id, cmd, args: qmp.append((cmd, args)) or {})
    rec.update(runs=runs, qmp=qmp, saved=saved)
    return rec


def test_resize_grows_the_primary_disk(client, auth_headers, vm):
    r = client.post("/api/vms/vm-1/disk/resize", json={"new_size_gb": 64}, headers=auth_headers)
    body = r.json()
    assert r.status_code == 200 and body["previous_size_gb"] == 32 and body["new_size_gb"] == 64
    assert vm["runs"][-1][1:] == ["resize", "-f", "qcow2", vm["disk_path"], "64G"]
    assert vm["saved"][-1][0]["disk_size_gb"] == 64
    assert vm["qmp"] == []


def test_resize_never_shrinks(client, auth_headers, vm):
    for size in (32, 16):
        r = client.post("/api/vms/vm-1/resize-disk", json={"new_size_gb": size}, headers=auth_headers)
        assert r.status_code == 400 and "shrinking" in r.json()["detail"]
    assert vm["runs"] == [] and vm["saved"] == []


def test_resize_creates_a_missing_secondary_raw_disk_and_tells_a_running_vm(client, auth_headers, vm):
    vm["running"] = True
    r = client.post("/api/vms/vm-1/disk/resize", json={"new_size_gb": 40, "disk_index": 1}, headers=auth_headers)
    assert r.status_code == 200
    assert vm["runs"][-1][1:4] == ["create", "-f", "raw"] and vm["runs"][-1][-1] == "40G"
    assert vm["qmp"] == [("block_resize", {"device": "sdisk0", "size": 40 * 1024**3})]
    assert vm["saved"][-1][0]["secondary_disks"][0]["size_gb"] == 40


def test_resize_unknown_vm_and_disk(client, auth_headers, vm):
    assert client.post("/api/vms/nope/disk/resize", json={"new_size_gb": 64}, headers=auth_headers).status_code == 404
    r = client.post("/api/vms/vm-1/disk/resize", json={"new_size_gb": 64, "disk_index": 3}, headers=auth_headers)
    assert r.status_code == 404


def test_resize_failure_changes_nothing(client, auth_headers, vm):
    vm["fail"] = True
    assert client.post("/api/vms/vm-1/disk/resize", json={"new_size_gb": 64}, headers=auth_headers).status_code == 500
    assert vm["saved"] == []
    r = client.post("/api/vms/vm-1/disk/resize", json={"new_size_gb": 64, "disk_index": 1}, headers=auth_headers)
    assert r.status_code == 500 and vm["saved"] == []
