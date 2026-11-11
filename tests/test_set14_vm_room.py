"""SET-14: a virtual machine that would take the memory or the disk space the NAS needs does not
start, and a failed automatic start is an event."""

from backend.services import vm_host

GB = 1024**3


def _vm(name, ram, state="stopped", **more):
    return {"id": name, "name": name, "ram_gb": ram, "state": state, **more}


def test_a_start_that_would_starve_the_nas_is_refused():
    running = [_vm("big", 10, "running")]
    # 16 GB, 2 GB kept for the NAS: 14 GB for machines, 10 of them in use
    assert vm_host.start_refusal(_vm("small", 4), running, 16 * GB, 50 * GB) == ""
    why = vm_host.start_refusal(_vm("second", 6), running, 16 * GB, 50 * GB)
    assert "second needs 6 GB of memory, and only 4 GB is left" in why and "keeps 2 GB for itself" in why
    assert vm_host.start_refusal(_vm("second", 6, override_active=True), running, 16 * GB, 50 * GB) == ""
    # the machine itself does not count against itself (a restart of a running one)
    assert vm_host.start_refusal(_vm("big", 10, "running"), running, 16 * GB, 50 * GB) == ""
    assert vm_host.start_refusal(_vm("x", 99), [], 0, 50 * GB) == ""  # memory not known: no refusal on a guess


def test_too_little_space_for_a_disk_to_grow():
    why = vm_host.start_refusal(_vm("vm", 1), [], 16 * GB, GB // 2)
    assert why.startswith("Only 0.5 GB is free in Kiboto's data folder, where the disk of vm is kept.")
    assert vm_host.start_refusal(_vm("vm", 1), [], 16 * GB, -1) == ""
    assert vm_host.create_refusal(64, "raw", 20 * GB).startswith("The new disk needs 64.0 GB and only 20.0 GB is free")
    assert vm_host.create_refusal(64, "qcow2", 20 * GB) == ""  # a growing disk starts small
    assert vm_host.create_refusal(64, "qcow2", GB // 4) != ""
    assert vm_host.disk_free_bytes() > 0


def test_the_route_refuses_a_start_with_the_reason(client, auth_headers, monkeypatch):
    from backend.api import vms as api_vms
    from backend.services import vm_qemu

    machine = _vm("vm-room1", 64)
    monkeypatch.setattr(vm_qemu, "_load_vms", lambda: [machine])
    monkeypatch.setattr(vm_host, "_get_host_memory_bytes", lambda: 16 * GB)
    started = []
    monkeypatch.setattr(vm_qemu, "_start_qemu", lambda *a, **k: started.append(a) or (True, ""))
    r = client.post("/api/vms/vm-room1/action", json={"action": "start"}, headers=auth_headers)
    assert r.status_code == 409 and "needs 64 GB of memory" in r.json()["detail"]
    assert r.json().get("error") == "vm_start_refused" and started == []
    assert api_vms.vm_host is vm_host


def test_a_failed_automatic_start_is_an_event(monkeypatch):
    import backend.main as main_mod
    from backend import state
    from backend.api import vms as api_vms
    from backend.services import vm_qemu

    machine = _vm("vm-auto1", 64, autostart=True)
    monkeypatch.setattr(api_vms, "_load_vms", lambda: [machine])
    monkeypatch.setattr(api_vms, "_is_qemu_process_alive", lambda _i: False)
    monkeypatch.setattr(api_vms, "_get_qemu_vnc_port", lambda *_a: 5900)
    monkeypatch.setattr(vm_host, "_get_host_memory_bytes", lambda: 16 * GB)
    monkeypatch.setattr(vm_qemu, "save_fields", lambda *a, **k: None)
    events = []
    monkeypatch.setattr(main_mod, "add_event", lambda *a, **k: events.append(a))
    monkeypatch.setattr("time.sleep", lambda _s: None)
    main_mod.autostart_vms()
    assert events and events[0][1] == "Virtual machine did not start" and "needs 64 GB" in events[0][2]
    assert state is not None
