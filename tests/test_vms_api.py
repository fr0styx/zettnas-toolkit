"""
Tests for Virtual Machines (VM) dynamic headroom budgeting, CPU overcommit,
KVM telemetry, and VM lifecycle actions.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api.vms import (
    calculate_cpu_capacity,
    calculate_vm_budget,
    get_kvm_status,
)


def test_dynamic_headroom_math_formula():
    # 8 GB Host: 10% is 0.8GB -> clamped to minimum 2.0GB reserve
    b8 = calculate_vm_budget(8 * (1024**3), [])
    assert b8["host_reserve_gb"] == 2.0
    assert b8["safe_max_vm_ram_gb"] == 6.0
    assert b8["safe_slider_max_gb"] == 6

    # 16 GB Host: 10% is 1.6GB -> clamped to minimum 2.0GB reserve
    b16 = calculate_vm_budget(16 * (1024**3), [])
    assert b16["host_reserve_gb"] == 2.0
    assert b16["safe_max_vm_ram_gb"] == 14.0
    assert b16["safe_slider_max_gb"] == 14

    # 32 GB Host: 10% is 3.2GB -> safe max is 28.8GB, integer clamp is 28GB
    b32 = calculate_vm_budget(32 * (1024**3), [])
    assert b32["host_reserve_gb"] == 3.2
    assert b32["safe_max_vm_ram_gb"] == 28.8
    assert b32["safe_slider_max_gb"] == 28

    # 96 GB Host: 10% is 9.6GB -> safe max is 86.4GB
    b96 = calculate_vm_budget(96 * (1024**3), [])
    assert b96["host_reserve_gb"] == 9.6
    assert b96["safe_max_vm_ram_gb"] == 86.4
    assert b96["safe_slider_max_gb"] == 86

    # 256 GB Host: 10% is 25.6GB -> safe max is 230.4GB
    b256 = calculate_vm_budget(256 * (1024**3), [])
    assert b256["host_reserve_gb"] == 25.6
    assert b256["safe_max_vm_ram_gb"] == 230.4
    assert b256["safe_slider_max_gb"] == 230


def test_cpu_thread_overcommit_states():
    host_threads = 8

    # 4 vCPUs on 8 threads -> 0.5x (Nominal)
    cap1 = calculate_cpu_capacity(host_threads, [{"state": "running", "vcpus": 4}])
    assert cap1["overcommit_ratio"] == 0.5
    assert cap1["status"] == "nominal"
    assert "1:1" in cap1["badge"]

    # 12 vCPUs on 8 threads -> 1.5x (Moderate Overcommit)
    cap2 = calculate_cpu_capacity(host_threads, [{"state": "running", "vcpus": 12}])
    assert cap2["overcommit_ratio"] == 1.5
    assert cap2["status"] == "moderate_overcommit"
    assert "1.5x" in cap2["badge"]

    # 20 vCPUs on 8 threads -> 2.5x (Heavy Overcommit)
    cap3 = calculate_cpu_capacity(host_threads, [{"state": "running", "vcpus": 20}])
    assert cap3["overcommit_ratio"] == 2.5
    assert cap3["status"] == "heavy_overcommit"
    assert "Heavy Overcommit: 2.5x" in cap3["badge"]


def test_kvm_status_inspection():
    status = get_kvm_status()
    assert "device_present" in status
    assert "hardware_virt" in status
    assert "state" in status
    assert status["state"] in ("active", "restricted", "disabled")


def test_kvm_status_active_when_rw():
    from unittest.mock import mock_open, patch

    def exists_side_effect(p):
        return p in ("/host/dev/kvm", "/dev/kvm", "/host/proc/cpuinfo", "/host/proc/modules")

    with (
        patch("backend.api.vms.os.path.exists", side_effect=exists_side_effect),
        patch("backend.api.vms.os.open", return_value=3),
        patch("backend.api.vms.os.close"),
        patch("backend.api.vms.os.symlink"),
        patch("builtins.open", mock_open(read_data="flags: vmx\nkvm 123\nkvm_intel 456\n")),
    ):
        status = get_kvm_status()
        assert status["state"] == "active"
        assert status["kvm_rw"] is True
        assert "KVM Accelerated: Active" in status["badge"]


def test_kvm_status_restricted_when_cgroup_eperm():
    from unittest.mock import mock_open, patch

    def exists_side_effect(p):
        return p in ("/host/dev/kvm", "/host/proc/cpuinfo", "/host/proc/modules")

    def mock_open_eperm(path, flags):
        raise PermissionError(1, "Operation not permitted")

    with (
        patch("backend.api.vms.os.path.exists", side_effect=exists_side_effect),
        patch("backend.api.vms.os.open", side_effect=mock_open_eperm),
        patch("backend.api.vms.os.symlink"),
        patch("builtins.open", mock_open(read_data="flags: vmx\nkvm 123\nkvm_intel 456\n")),
    ):
        status = get_kvm_status()
        assert status["state"] == "restricted"
        assert status["cgroup_restricted"] is True
        assert "Docker cgroup restricted" in status["badge"]


def test_vms_api_crud_and_validation(client, auth_headers):
    # 1. Telemetry endpoint
    res = client.get("/api/vms/telemetry", headers=auth_headers)
    assert res.status_code == 200
    tel = res.json()
    assert "kvm" in tel
    assert "memory_budget" in tel
    assert "cpu_capacity" in tel

    # 2. List VMs
    res = client.get("/api/vms", headers=auth_headers)
    assert res.status_code == 200
    vms = res.json()
    assert isinstance(vms, list)

    # 3. Create VM exceeding safe headroom without override -> Rejected
    over_budget_ram = tel["memory_budget"]["safe_headroom_gb"] + 50.0
    bad_req = {
        "name": "too-large-vm",
        "vcpus": 4,
        "ram_gb": over_budget_ram,
        "disk_size_gb": 32,
        "override_limits": False,
    }
    res = client.post("/api/vms", json=bad_req, headers=auth_headers)
    assert res.status_code == 400
    assert "exceeds safe headroom" in res.json()["detail"]

    # 4. Create VM with valid allocation
    good_req = {
        "name": "test-alpine-node",
        "description": "Lightweight Microservice VM",
        "os_family": "linux",
        "vcpus": 2,
        "ram_gb": 1.0,
        "disk_size_gb": 10,
        "override_limits": False,
    }
    res = client.post("/api/vms", json=good_req, headers=auth_headers)
    assert res.status_code == 200
    created = res.json()
    assert created["name"] == "test-alpine-node"
    assert created["state"] == "stopped"
    vm_id = created["id"]

    # 5. Create VM with volume mappings & secondary disks
    mapped_req = {
        "name": "test-virtiofs-vm",
        "description": "VM with VirtIO-FS and secondary disk",
        "os_family": "linux",
        "vcpus": 2,
        "ram_gb": 2.0,
        "disk_size_gb": 20,
        "host_shares": [
            {
                "host_path": "/mnt/user/appdata",
                "mount_tag": "appdata_share",
                "driver": "virtiofs",
                "mode": "rw",
            }
        ],
        "secondary_disks": [
            {
                "name": "data-vol-1",
                "size_gb": 40,
                "format": "qcow2",
                "bus": "virtio",
            }
        ],
    }
    res = client.post("/api/vms", json=mapped_req, headers=auth_headers)
    assert res.status_code == 200
    mapped_vm = res.json()
    assert len(mapped_vm["host_shares"]) == 1
    assert mapped_vm["host_shares"][0]["mount_tag"] == "appdata_share"
    assert len(mapped_vm["secondary_disks"]) == 1

    # 6. Lifecycle Action: start -> running
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "start"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # 7. Connection info endpoint (SSH command, VNC, console)
    res = client.get(f"/api/vms/{vm_id}/connection-info", headers=auth_headers)
    assert res.status_code == 200
    conn = res.json()
    assert conn["vm_id"] == vm_id
    assert "ssh_command" in conn
    assert "vnc_port" in conn
    assert "vnc_uri" in conn
    assert conn["has_ip"] is True

    # 8. Console token generation
    res = client.post(f"/api/vms/{vm_id}/console/token", headers=auth_headers)
    assert res.status_code == 200
    tok = res.json()
    assert "ticket" in tok
    assert tok["ticket"].startswith("zct_")
    assert "ws_url" in tok

    # 9. Official ISO Catalog and download task
    res = client.get("/api/vms/catalog", headers=auth_headers)
    assert res.status_code == 200
    catalog = res.json()
    assert len(catalog) >= 5
    ubuntu_item = next((c for c in catalog if c["id"] == "ubuntu-2404"), None)
    assert ubuntu_item is not None
    assert "download_url" in ubuntu_item
    assert "downloaded" in ubuntu_item

    # Start catalog download task
    res = client.post("/api/vms/catalog/ubuntu-2404/download", headers=auth_headers)
    assert res.status_code == 200
    dl_res = res.json()
    assert dl_res["status"] in ("started", "already_present")

    # Catalog tasks listing
    res = client.get("/api/vms/catalog/tasks", headers=auth_headers)
    assert res.status_code == 200
    tasks = res.json()
    assert isinstance(tasks, list)

    # Cancel/remove catalog task
    if tasks and "task_id" in tasks[0]:
        t_id = tasks[0]["task_id"]
        del_task_res = client.delete(f"/api/vms/catalog/tasks/{t_id}", headers=auth_headers)
        assert del_task_res.status_code == 200
        assert del_task_res.json()["status"] in ("cancelling", "removed")

    # 10. Individual VM detail endpoint
    res = client.get(f"/api/vms/{vm_id}", headers=auth_headers)
    assert res.status_code == 200
    detail = res.json()
    assert detail["id"] == vm_id
    assert "vnc_port" in detail
    assert "connection_summary" in detail

    res = client.get("/api/vms/vm-nonexistent-id", headers=auth_headers)
    assert res.status_code == 404

    # 11. Streaming ISO upload with SHA-256 and format verification
    sample_content = b"TEST_ISO_CONTENT_" * 64
    res = client.post(
        "/api/vms/isos/upload",
        content=sample_content,
        headers={**auth_headers, "x-filename": "test-sample.iso"},
    )
    assert res.status_code == 200
    up_res = res.json()
    assert up_res["filename"] == "test-sample.iso"
    assert "sha256" in up_res
    assert len(up_res["sha256"]) == 64
    assert up_res["size_bytes"] == len(sample_content)

    # Cleanup test upload
    client.delete(f"/api/vms/isos?path={up_res['path']}", headers=auth_headers)

    # 12. WebSocket ticket validation and single-use consumption
    from backend.api.vms import _validate_console_ticket

    assert _validate_console_ticket(tok["ticket"], vm_id) is True
    # Second validation attempt fails because single-use ticket was consumed
    assert _validate_console_ticket(tok["ticket"], vm_id) is False
    assert _validate_console_ticket("invalid_ticket", vm_id) is False

    # 13. Detailed KVM Diagnose endpoint with kvm_api_version
    res = client.get("/api/vms/kvm/diagnose", headers=auth_headers)
    assert res.status_code == 200
    diag = res.json()
    assert "hardware_virt" in diag
    assert "cgroup_restricted" in diag
    assert "badge" in diag
    assert "kvm_api_version" in diag

    # 14. Action: pause -> paused
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "pause"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "paused"

    # 15. Action: stop -> stopped
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "stop"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "stopped"

    # 16. Delete stopped VMs
    res = client.delete(f"/api/vms/{vm_id}", headers=auth_headers)
    assert res.status_code == 200
    res = client.delete(f"/api/vms/{mapped_vm['id']}", headers=auth_headers)
    assert res.status_code == 200


def test_vm_reconciliation_cleans_phantom_running(client, auth_headers):
    """Verifies that unmonitored or dead VMs marked 'running' are reconciled to 'stopped'."""
    from backend.api.vms import _load_vms, _save_vms

    # Create test VM
    res = client.post(
        "/api/vms",
        json={"name": "phantom-test-vm", "vcpus": 1, "ram_gb": 1.0, "disk_size_gb": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    vm_id = res.json()["id"]

    # Directly simulate a stale persisted state of "running" without active process
    vms = _load_vms()
    for v in vms:
        if v["id"] == vm_id:
            v["state"] = "running"
            v["uptime_seconds"] = 1200
    _save_vms(vms)

    # Calling list_vms must reconcile to stopped
    res = client.get("/api/vms", headers=auth_headers)
    assert res.status_code == 200
    updated_vms = res.json()
    target = next((v for v in updated_vms if v["id"] == vm_id), None)
    assert target is not None
    assert target["state"] == "stopped"
    assert target["uptime_seconds"] == 0

    # Clean up
    client.delete(f"/api/vms/{vm_id}", headers=auth_headers)


def test_vm_start_failure_raises_500_and_captures_error(client, auth_headers):
    """Verifies that if QEMU startup fails, HTTP 500 is returned, state stays stopped, and error is logged."""
    from unittest.mock import patch

    res = client.post(
        "/api/vms",
        json={"name": "fail-test-vm", "vcpus": 1, "ram_gb": 1.0, "disk_size_gb": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    vm_id = res.json()["id"]

    simulated_err = "Could not access KVM kernel module: Operation not permitted"
    with patch("backend.api.vms._start_qemu", return_value=(False, simulated_err)):
        action_res = client.post(f"/api/vms/{vm_id}/action", json={"action": "start"}, headers=auth_headers)
        assert action_res.status_code == 500
        assert simulated_err in action_res.json()["detail"]

    # Verify error query endpoint returns the captured error
    err_res = client.get(f"/api/vms/{vm_id}/error", headers=auth_headers)
    assert err_res.status_code == 200
    err_data = err_res.json()
    assert err_data["has_error"] is True
    assert simulated_err in err_data["last_error"]

    # Clean up
    client.delete(f"/api/vms/{vm_id}", headers=auth_headers)


def test_vm_expanded_lifecycle_actions(client, auth_headers):
    """Tests restart, reboot, acpi_shutdown, and force_off lifecycle actions."""
    res = client.post(
        "/api/vms",
        json={"name": "lifecycle-test-vm", "vcpus": 1, "ram_gb": 1.0, "disk_size_gb": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    vm_id = res.json()["id"]

    # Start
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "start"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # Restart
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "restart"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # Reboot
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "reboot"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # ACPI Shutdown
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "acpi_shutdown"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "stopped"

    # Start and Force Off
    client.post(f"/api/vms/{vm_id}/action", json={"action": "start"}, headers=auth_headers)
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "force_off"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "stopped"

    # Clean up
    client.delete(f"/api/vms/{vm_id}", headers=auth_headers)


def test_vm_disk_resize_endpoint(client, auth_headers):
    """Tests virtual disk expansion endpoint and validation rules."""
    res = client.post(
        "/api/vms",
        json={"name": "resize-test-vm", "vcpus": 1, "ram_gb": 1.0, "disk_size_gb": 15},
        headers=auth_headers,
    )
    assert res.status_code == 200
    vm_id = res.json()["id"]

    # Shrinking must fail with 400
    res = client.post(f"/api/vms/{vm_id}/disk/resize", json={"new_size_gb": 10}, headers=auth_headers)
    assert res.status_code == 400
    assert "must be larger than current size" in res.json()["detail"]

    # Expansion succeeds
    res = client.post(f"/api/vms/{vm_id}/disk/resize", json={"new_size_gb": 30}, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["previous_size_gb"] == 15
    assert data["new_size_gb"] == 30

    # Verify detail shows updated disk size
    detail = client.get(f"/api/vms/{vm_id}", headers=auth_headers).json()
    assert detail["disk_size_gb"] == 30

    # Clean up
    client.delete(f"/api/vms/{vm_id}", headers=auth_headers)


def test_vm_qmp_status_endpoint(client, auth_headers):
    """Tests QMP status inquiry endpoint."""
    res = client.post(
        "/api/vms",
        json={"name": "qmp-status-vm", "vcpus": 1, "ram_gb": 1.0, "disk_size_gb": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    vm_id = res.json()["id"]

    # Query status of stopped VM
    res = client.get(f"/api/vms/{vm_id}/status", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["vm_id"] == vm_id
    assert data["state"] == "stopped"
    assert data["running"] is False

    # Clean up
    client.delete(f"/api/vms/{vm_id}", headers=auth_headers)


def test_vm_direct_action_endpoints(client, auth_headers):
    """Tests convenience endpoints /{vm_id}/start, /{vm_id}/stop, and /{vm_id}/restart."""
    res = client.post(
        "/api/vms",
        json={"name": "direct-action-vm", "vcpus": 1, "ram_gb": 1.0, "disk_size_gb": 10},
        headers=auth_headers,
    )
    assert res.status_code == 200
    vm_id = res.json()["id"]

    # Test direct POST /api/vms/{vm_id}/start
    res = client.post(f"/api/vms/{vm_id}/start", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # Test direct POST /api/vms/{vm_id}/restart
    res = client.post(f"/api/vms/{vm_id}/restart", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # Test direct POST /api/vms/{vm_id}/stop
    res = client.post(f"/api/vms/{vm_id}/stop", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "stopped"

    # Clean up
    client.delete(f"/api/vms/{vm_id}", headers=auth_headers)


def test_unmatched_api_route_returns_404_not_405(client, auth_headers):
    """Verifies that non-existent /api routes return 404 rather than falling through to StaticFiles 405."""
    res = client.post("/api/vms/nonexistent-vm-xyz/fake-subpath", headers=auth_headers)
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()
