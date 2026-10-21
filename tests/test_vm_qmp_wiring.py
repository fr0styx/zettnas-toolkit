"""vms.py routes QMP through the persistent engine with correct arguments."""

import asyncio
import inspect
from unittest.mock import patch

import backend.api.vms as vms


class Recorder:
    def __init__(self, reply=None):
        self.calls = []
        self.reply = reply or {"return": {}}

    def execute(self, vm_id, command, arguments=None, timeout=2.5):
        self.calls.append((vm_id, command, arguments, timeout))
        return self.reply

    def close(self, vm_id):
        self.calls.append((vm_id, "__close__", None, None))

    def watch(self, vm_id):
        pass


def test_qmp_command_delegates_to_engine():
    rec = Recorder({"return": {"status": "running"}})
    with patch.object(vms, "_QMP_ENGINE", rec):
        assert vms._qmp_command("vm1", "query-status") == {"return": {"status": "running"}}
        vms._qmp_command("vm1", "human-monitor-command", {"command-line": "info"}, 10.0)
    assert rec.calls == [
        ("vm1", "query-status", None, 2.5),
        ("vm1", "human-monitor-command", {"command-line": "info"}, 10.0),
    ]


def test_graceful_stop_sends_powerdown_without_bogus_arguments():
    rec = Recorder()
    with (
        patch.object(vms, "_QMP_ENGINE", rec),
        patch.object(vms, "_is_qemu_process_alive", return_value=False),
        patch.object(vms, "_sync_cleanup_qemu_process"),
    ):
        asyncio.run(vms.async_stop_qemu("vm1", force=False))
    assert rec.calls[0] == ("vm1", "system_powerdown", None, 1.5)


def test_snapshot_monitor_commands_pass_arguments_then_timeout():
    src = inspect.getsource(vms)
    assert '"human-monitor-command", 10.0' not in src
    assert src.count('"human-monitor-command", {"command-line": cmd_str}, 10.0)') == 3


def test_cleanup_closes_engine_connection():
    rec = Recorder()
    with patch.object(vms, "_QMP_ENGINE", rec):
        vms._sync_cleanup_qemu_process("vm-cleanup-test", force=True)
    assert ("vm-cleanup-test", "__close__", None, None) in rec.calls


def test_qmp_events_are_logged():
    with (
        patch.object(vms, "_load_vms", return_value=[{"id": "vm1", "name": "win11"}]),
        patch.object(vms, "add_event") as add_event,
    ):
        vms._on_qmp_event("vm1", "GUEST_PANICKED", {"action": "pause"})
        vms._on_qmp_event("vm1", "SHUTDOWN", {"guest": True, "reason": "guest-shutdown"})
        vms._on_qmp_event("vm1", "SHUTDOWN", {"guest": False, "reason": "host-qmp-quit"})
        vms._on_qmp_event("vm1", "RESUME", {})
    titles = [c.args[1] for c in add_event.call_args_list]
    assert titles == ["VM Guest Crashed", "VM Shut Down"]
    assert "win11" in add_event.call_args_list[0].args[2]
