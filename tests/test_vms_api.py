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

    # 5. Lifecycle Action: start -> running
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "start"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "running"

    # 6. Action: pause -> paused
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "pause"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "paused"

    # 7. Action: stop -> stopped
    res = client.post(f"/api/vms/{vm_id}/action", json={"action": "stop"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["state"] == "stopped"

    # 8. Delete stopped VM
    res = client.delete(f"/api/vms/{vm_id}", headers=auth_headers)
    assert res.status_code == 200
