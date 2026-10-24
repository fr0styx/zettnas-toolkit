"""Starting QEMU (test shortcut off): the command line for each VM setting, and every way a start fails."""

import os
import uuid

import pytest

from backend.services import vm_host, vm_qemu, vm_store


class FakeProc:
    def __init__(self, exit_code=None, err=b""):
        self.exit_code = exit_code
        self.err = err
        self.pid = 4242

    def poll(self):
        return self.exit_code

    def communicate(self):
        return b"", self.err


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A host with qemu installed, no KVM and no bridge; records the commands started."""
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)
    qemu = tmp_path / "qemu-system-x86_64"
    qemu.write_text("")
    taskset = tmp_path / "taskset"
    taskset.write_text("")
    monkeypatch.setattr(
        vm_qemu.shutil, "which", lambda name: {"qemu-system-x86_64": str(qemu), "taskset": str(taskset)}.get(name)
    )
    monkeypatch.setattr(vm_host, "_pci_passthrough_problem", lambda vm: None)
    monkeypatch.setattr(vm_store, "_primary_disk_problem", lambda vm, path: None)
    monkeypatch.setattr(vm_host, "_can_use_kvm", lambda: False)
    monkeypatch.setattr(vm_host, "scan_bridges", lambda: [])
    monkeypatch.setattr(vm_host, "_sanitize_pci_list", lambda lst: lst or [])
    monkeypatch.setattr(vm_store, "_confined", lambda path, roots, kind: path)
    monkeypatch.setattr(vm_qemu.time, "sleep", lambda s: None)
    monkeypatch.setattr(vm_qemu._QMP_ENGINE, "watch", lambda vm_id: None)
    monkeypatch.setattr(vm_qemu.threading, "Thread", lambda **kw: type("T", (), {"start": lambda self: None})())
    started = []
    procs = []

    def popen(cmd, **kw):
        started.append(cmd)
        return procs.pop(0) if procs else FakeProc()

    monkeypatch.setattr(vm_qemu.subprocess, "Popen", popen)
    monkeypatch.setattr(vm_store, "_RUNNING_QEMU_PROCS", {})
    monkeypatch.setattr(vm_store, "_LAST_QEMU_ERRORS", {})
    return {"started": started, "procs": procs, "tmp": tmp_path}


def vm(tmp_path, **extra):
    vm_id = "vm-" + uuid.uuid4().hex[:6]
    disk = tmp_path / f"{vm_id}.qcow2"
    disk.write_text("")
    return {"id": vm_id, "name": "Test VM", "ram_gb": 2, "vcpus": 2, "disk_path": str(disk), **extra}


def args(cmd):
    return " ".join(cmd)


class TestCommandLine:
    def test_basic_vm_without_kvm(self, host):
        target = vm(host["tmp"])
        ok, err = vm_qemu._start_qemu(target, 5901)
        assert ok and err is None
        line = args(host["started"][0])
        assert "-m 2048" in line and "-smp 2" in line and "-accel tcg -cpu qemu64" in line
        assert "-vnc 127.0.0.1:1" in line and "-boot order=c" in line and "-vga virtio" in line
        assert "user,id=net0,hostfwd=tcp::2221-:22" in line and target["network_mode"] == "slirp"
        assert vm_store._RUNNING_QEMU_PROCS[target["id"]]["pid"] == 4242

    def test_kvm_topology_uefi_and_iso(self, host, monkeypatch):
        monkeypatch.setattr(vm_host, "_can_use_kvm", lambda: True)
        code = host["tmp"] / "OVMF_CODE.fd"
        code.write_text("")
        vars_tpl = host["tmp"] / "OVMF_VARS.fd"
        vars_tpl.write_text("")
        monkeypatch.setattr(vm_host, "_find_ovmf_firmware", lambda: (str(code), str(vars_tpl)))
        iso = host["tmp"] / "debian.iso"
        iso.write_text("")
        target = vm(
            host["tmp"], vcpus=8, sockets=1, cores=4, threads=2, firmware="uefi", iso_path=str(iso), video_adapter="qxl"
        )
        assert vm_qemu._start_qemu(target, 5902)[0]
        line = args(host["started"][0])
        assert "-enable-kvm -cpu host" in line and "-smp 8,sockets=1,cores=4,threads=2" in line
        assert f"if=pflash,format=raw,readonly=on,file={code}" in line and "OVMF_VARS.fd" in line
        assert f"-cdrom {iso} -boot order=dc,menu=on" in line and "-vga qxl" in line
        assert target["acceleration"] == "kvm"

    @pytest.mark.parametrize(
        "adapter, flag", [("none", "-vga none"), ("vga", "-vga std"), ("virtio-gpu", "-vga virtio")]
    )
    def test_video_adapters(self, host, adapter, flag):
        vm_qemu._start_qemu(vm(host["tmp"], video_adapter=adapter), 5903)
        assert flag in args(host["started"][0])

    def test_shares_disks_usb_pci_tpm_and_affinity(self, host, monkeypatch):
        share = host["tmp"] / "media"
        share.mkdir()
        second = host["tmp"] / "data.qcow2"
        second.write_text("")
        monkeypatch.setattr(vm_qemu, "_prepare_vtpm", lambda vm_id, vm_dir: ["-tpmdev", "emulator,id=tpm0"])
        target = vm(
            host["tmp"],
            host_shares=[
                {"host_path": str(share), "mount_tag": "my media!", "mode": "ro"},
                {"host_path": "/nonexistent"},
            ],
            secondary_disks=[{"path": str(second), "bus": "virtio"}],
            usb_passthrough=[{"vendor_id": "0x051d", "product_id": "0002"}, {"vendor_id": "zzzz", "product_id": "1"}],
            pci_passthrough=[{"slot": "0000:01:00.0"}],
            tpm_enabled=True,
            cpu_affinity=[2, 3],
        )
        assert vm_qemu._start_qemu(target, 5904)[0]
        cmd = host["started"][0]
        line = args(cmd)
        assert cmd[0].endswith("taskset") and cmd[1:3] == ["-c", "2,3"]
        assert f"path={share},security_model=none,readonly=on" in line and "mount_tag=my_media_" in line
        assert f"file={second},if=virtio,format=qcow2,id=sdisk0" in line
        assert "usb-host,vendorid=0x051d,productid=0x0002" in line and "zzzz" not in line
        assert "vfio-pci,host=0000:01:00.0" in line and "-tpmdev emulator,id=tpm0" in line

    def test_bridge_networking(self, host, monkeypatch):
        helper = host["tmp"] / "qemu-bridge-helper"
        helper.write_text("")
        helper.chmod(0o755)
        monkeypatch.setattr(vm_host, "scan_bridges", lambda: ["br0"])
        real_exists, real_access = vm_qemu.os.path.exists, vm_qemu.os.access
        monkeypatch.setattr(
            vm_qemu.os.path,
            "exists",
            lambda p: True if p in ("/dev/net/tun", "/usr/lib/qemu/qemu-bridge-helper") else real_exists(p),
        )
        monkeypatch.setattr(
            vm_qemu.os,
            "access",
            lambda p, m: True if p in ("/dev/net/tun", "/usr/lib/qemu/qemu-bridge-helper") else real_access(p, m),
        )
        target = vm(host["tmp"], mac="52:54:00:aa:bb:cc")
        assert vm_qemu._start_qemu(target, 5905)[0]
        assert "bridge,id=net0,br=br0" in args(host["started"][0]) and target["network_mode"] == "bridge"

    def test_bridge_failure_falls_back_to_slirp(self, host, monkeypatch):
        monkeypatch.setattr(vm_host, "scan_bridges", lambda: ["br0"])
        real_exists, real_access = vm_qemu.os.path.exists, vm_qemu.os.access
        monkeypatch.setattr(
            vm_qemu.os.path,
            "exists",
            lambda p: True if p in ("/dev/net/tun", "/usr/lib/qemu/qemu-bridge-helper") else real_exists(p),
        )
        monkeypatch.setattr(
            vm_qemu.os,
            "access",
            lambda p, m: True if p in ("/dev/net/tun", "/usr/lib/qemu/qemu-bridge-helper") else real_access(p, m),
        )
        host["procs"].extend([FakeProc(exit_code=1, err=b"failed to create tun device"), FakeProc()])
        target = vm(host["tmp"])
        assert vm_qemu._start_qemu(target, 5906)[0]
        assert "bridge" in args(host["started"][0]) and "user,id=net0" in args(host["started"][1])
        assert target["network_mode"] == "slirp"


class TestFailures:
    def test_no_qemu_on_the_core_image(self, host, monkeypatch):
        monkeypatch.setattr(vm_qemu.shutil, "which", lambda name: None)
        real_exists = vm_qemu.os.path.exists
        monkeypatch.setattr(
            vm_qemu.os.path, "exists", lambda p: False if p.endswith("qemu-system-x86_64") else real_exists(p)
        )
        monkeypatch.setattr(vm_host, "_image_variant", lambda: "core")
        target = vm(host["tmp"])
        ok, err = vm_qemu._start_qemu(target, 5907)
        assert not ok and "core ZettNAS image" in err and target["last_error"] == err

    def test_pci_problem(self, host, monkeypatch):
        monkeypatch.setattr(vm_host, "_pci_passthrough_problem", lambda vm: "IOMMU is off")
        assert vm_qemu._start_qemu(vm(host["tmp"]), 5908) == (False, "IOMMU is off")

    def test_disk_problem(self, host, monkeypatch):
        monkeypatch.setattr(vm_store, "_primary_disk_problem", lambda vm, path: "disk outside storage")
        assert vm_qemu._start_qemu(vm(host["tmp"]), 5909) == (False, "disk outside storage")

    def test_new_disk_cannot_be_created(self, host, monkeypatch):
        def fail(*a, **k):
            raise OSError("qemu-img missing")

        monkeypatch.setattr(vm_qemu.subprocess, "run", fail)
        target = vm(host["tmp"])
        os.remove(target["disk_path"])
        ok, err = vm_qemu._start_qemu(target, 5910)
        assert not ok and "Failed to initialize primary disk" in err

    def test_qemu_exits_at_once(self, host):
        host["procs"].append(FakeProc(exit_code=1, err=b"could not open disk image"))
        ok, err = vm_qemu._start_qemu(vm(host["tmp"]), 5911)
        assert not ok and err == "could not open disk image"

    def test_spawn_error(self, host, monkeypatch):
        def boom(cmd, **kw):
            raise PermissionError("not allowed")

        monkeypatch.setattr(vm_qemu.subprocess, "Popen", boom)
        assert vm_qemu._start_qemu(vm(host["tmp"]), 5912) == (False, "not allowed")

    def test_already_running(self, host, monkeypatch):
        target = vm(host["tmp"])
        vm_store._RUNNING_QEMU_PROCS[target["id"]] = {"proc": FakeProc(), "pid": 1}
        assert vm_qemu._start_qemu(target, 5913) == (True, None) and host["started"] == []


class TestProcessState:
    def test_alive_and_gone(self, host, monkeypatch):
        vm_store._RUNNING_QEMU_PROCS["a"] = {"proc": FakeProc()}
        vm_store._RUNNING_QEMU_PROCS["b"] = {"proc": FakeProc(exit_code=0)}
        assert vm_qemu._is_qemu_process_alive("a")
        assert not vm_qemu._is_qemu_process_alive("b") and "b" not in vm_store._RUNNING_QEMU_PROCS

    def test_by_pid_file(self, host, monkeypatch):
        vm_dir = os.path.join(vm_qemu.DATA_DIR, "vms", "pidvm")
        os.makedirs(vm_dir, exist_ok=True)
        with open(os.path.join(vm_dir, "qemu.pid"), "w") as f:
            f.write(str(os.getpid()))
        assert vm_qemu._is_qemu_process_alive("pidvm")
        with open(os.path.join(vm_dir, "qemu.pid"), "w") as f:
            f.write("999999999")
        assert not vm_qemu._is_qemu_process_alive("pidvm")
        assert not os.path.exists(os.path.join(vm_dir, "qemu.pid"))
