"""vTPM 2.0 (swtpm) launch path for VMs."""

import os
from unittest.mock import MagicMock, patch

import backend.api.vms as vms
import backend.services.vm_host as vm_host


class FakeProc:
    def __init__(self, sock_path=None, exit_code=None):
        self._sock = sock_path
        self.returncode = exit_code
        self.killed = False

    def poll(self):
        if self._sock:
            open(self._sock, "w").close()
        return self.returncode

    def kill(self):
        self.killed = True


def test_missing_swtpm_returns_no_args(tmp_path):
    with patch.object(vm_host, "_swtpm_binary", return_value=None):
        assert vms._prepare_vtpm("vm1", str(tmp_path)) == []


def test_swtpm_args_attached_once_socket_appears(tmp_path):
    sock = os.path.join(str(tmp_path), "tpm", "swtpm.sock")
    popen = MagicMock(side_effect=lambda cmd, **kw: FakeProc(sock_path=sock))
    with (
        patch.object(vm_host, "_swtpm_binary", return_value="/usr/bin/swtpm"),
        patch.object(vms.subprocess, "Popen", popen),
    ):
        args = vms._prepare_vtpm("vm1", str(tmp_path))

    cmd = popen.call_args[0][0]
    assert cmd[:2] == ["/usr/bin/swtpm", "socket"]
    assert "--tpm2" in cmd and f"type=unixio,path={sock}" in cmd
    assert args == [
        "-chardev",
        f"socket,id=chrtpm,path={sock}",
        "-tpmdev",
        "emulator,id=tpm0,chardev=chrtpm",
        "-device",
        "tpm-tis,tpmdev=tpm0",
    ]


def test_stale_socket_is_removed_before_start(tmp_path):
    tpm_dir = tmp_path / "tpm"
    tpm_dir.mkdir()
    stale = tpm_dir / "swtpm.sock"
    stale.write_text("")
    seen = {}

    def fake_popen(cmd, **kw):
        seen["stale_present"] = stale.exists()
        return FakeProc(sock_path=str(stale))

    with (
        patch.object(vm_host, "_swtpm_binary", return_value="/usr/bin/swtpm"),
        patch.object(vms.subprocess, "Popen", fake_popen),
    ):
        assert vms._prepare_vtpm("vm1", str(tmp_path))
    assert seen["stale_present"] is False


def test_swtpm_exiting_early_boots_without_tpm(tmp_path):
    with (
        patch.object(vm_host, "_swtpm_binary", return_value="/usr/bin/swtpm"),
        patch.object(vms.subprocess, "Popen", return_value=FakeProc(exit_code=1)),
    ):
        assert vms._prepare_vtpm("vm1", str(tmp_path)) == []


def test_swtpm_socket_timeout_kills_daemon(tmp_path):
    proc = FakeProc()
    with (
        patch.object(vm_host, "_swtpm_binary", return_value="/usr/bin/swtpm"),
        patch.object(vms.subprocess, "Popen", return_value=proc),
    ):
        assert vms._prepare_vtpm("vm1", str(tmp_path), wait_secs=0.1) == []
    assert proc.killed


def test_popen_failure_boots_without_tpm(tmp_path):
    with (
        patch.object(vm_host, "_swtpm_binary", return_value="/usr/bin/swtpm"),
        patch.object(vms.subprocess, "Popen", side_effect=OSError("exec format error")),
    ):
        assert vms._prepare_vtpm("vm1", str(tmp_path)) == []


def test_kvm_status_reports_vtpm_availability():
    with patch.object(vm_host, "_swtpm_binary", return_value=None):
        assert vms.get_kvm_status()["vtpm_available"] is False
    with patch.object(vm_host, "_swtpm_binary", return_value="/usr/bin/swtpm"):
        assert vms.get_kvm_status()["vtpm_available"] is True
