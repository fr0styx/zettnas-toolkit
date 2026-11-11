"""SET-07: before Kiboto restarts, updates or turns the NAS off, running virtual machines are
asked to shut down and waited for. They used to be killed with it."""

import json

import pytest

from backend.api import system as system_api
from backend.services import vm_qemu, vm_store


@pytest.fixture
def machines(tmp_path, monkeypatch):
    path = tmp_path / "vms.json"
    monkeypatch.setattr(vm_store, "VMS_CONFIG_FILE", str(path))
    state = {"alive": {"a", "p", "stuck"}, "qmp": [], "killed": [], "events": [], "deaf": set()}
    path.write_text(
        json.dumps(
            [
                {"id": "a", "name": "alpha", "state": "running"},
                {"id": "p", "name": "paused-one", "state": "paused"},
                {"id": "stuck", "name": "stuck-one", "state": "running"},
                {"id": "off", "name": "off-one", "state": "stopped"},
            ]
        )
    )

    def qmp(vm_id, cmd, *a, **k):
        state["qmp"].append((vm_id, cmd))
        if cmd == "system_powerdown":
            if vm_id in state["deaf"]:
                return {"error": "no monitor"}
            if vm_id != "stuck":
                state["alive"].discard(vm_id)  # the system inside shuts down
        return {"return": {}}

    def kill(vm_id, force=False):
        state["killed"].append((vm_id, force))
        state["alive"].discard(vm_id)

    clock = {"t": 0.0}
    monkeypatch.setattr(vm_qemu, "_is_qemu_process_alive", lambda vm_id: vm_id in state["alive"])
    monkeypatch.setattr(vm_qemu, "_qmp_command", qmp)
    monkeypatch.setattr(vm_qemu, "_sync_cleanup_qemu_process", kill)
    monkeypatch.setattr(vm_qemu, "_forget_process", lambda vm_id: None)
    monkeypatch.setattr(vm_qemu, "add_event", lambda *a, **k: state["events"].append(a))
    monkeypatch.setattr(vm_qemu.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(vm_qemu.time, "sleep", lambda s: clock.update(t=clock["t"] + s))
    state["read"] = lambda: {v["id"]: v for v in json.loads(path.read_text())}
    state["clock"] = clock
    return state


def test_every_running_machine_is_asked_and_waited_for(machines):
    done = vm_qemu.shut_down_all()
    assert ("p", "cont") in machines["qmp"]  # a frozen machine hears nothing
    assert [m for m, c in machines["qmp"] if c == "system_powerdown"] == ["a", "p", "stuck"]
    assert done == {"shut_down": ["alpha", "paused-one"], "turned_off": ["stuck-one"]}
    assert machines["clock"]["t"] >= vm_qemu.SHUTDOWN_GRACE  # the one that hangs got its two minutes
    assert machines["killed"] == [("stuck", True)]
    assert machines["events"][0][0] == "warning" and "stuck-one" in machines["events"][0][2]
    now = machines["read"]()
    assert {k: v["state"] for k, v in now.items()} == {
        "a": "stopped",
        "p": "stopped",
        "stuck": "stopped",
        "off": "stopped",
    }
    assert now["a"]["start_again"] and now["stuck"]["start_again"] and "start_again" not in now["off"]


def test_nothing_waits_when_all_shut_down_or_none_listens(machines):
    machines["alive"].discard("stuck")
    assert vm_qemu.shut_down_all()["turned_off"] == []
    assert machines["clock"]["t"] == 0 and machines["killed"] == []

    machines["alive"].update({"a"})
    machines["deaf"].add("a")
    vm_qemu.save_fields("a", {"state": "running"})
    assert vm_qemu.shut_down_all() == {"shut_down": [], "turned_off": ["alpha"]}
    assert machines["clock"]["t"] == 0  # waiting does not make a machine with no monitor shut down


def test_stopped_from_outside_nothing_is_killed_and_the_wish_to_come_back_is_saved_first(machines):
    done = vm_qemu.shut_down_all(turn_off=False)
    assert done == {"shut_down": ["alpha", "paused-one"], "turned_off": []}
    assert machines["killed"] == []
    stuck = machines["read"]()["stuck"]
    assert stuck["state"] == "shutting_down" and stuck["start_again"] is True


def test_a_shutdown_of_the_nas_brings_back_only_what_starts_with_it(machines):
    vm_qemu.shut_down_all(come_back=False)
    assert "start_again" not in machines["read"]()["a"]


def test_the_power_and_update_routes_ask_the_machines_first(monkeypatch):
    import inspect

    for fn in (
        system_api.system_reboot,
        system_api.system_shutdown,
        system_api.post_apply_system_update,
        system_api.post_revert_system_update,
    ):
        src = inspect.getsource(fn)
        assert "machines_first" in src, fn.__name__
        first = src.index("machines_first")
        later = max(src.find("trigger_power_action"), src.find("spawn_self_updater, "))
        assert first < later, fn.__name__
    seen = []
    monkeypatch.setattr(vm_qemu, "shut_down_all", lambda **kw: seen.append(kw))
    system_api.machines_first()
    system_api.machines_first(False)
    assert seen == [{"come_back": True}, {"come_back": False}]
