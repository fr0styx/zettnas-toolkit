"""
QEMU process lifecycle: building the command line, starting and stopping VMs,
QMP, and keeping vms.json in step with the processes that are actually running.

Split out of backend/api/vms.py (ARC-01); the API re-exports these names.
"""

import asyncio
import functools
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth import AuthenticatedPrincipal, get_current_principal, require_scope
from backend.config import DATA_DIR, HOST_PROC, POOL_PATH, VM_ISO_DIR, logger
from backend.confirmations import require_confirmation
from backend.fsutil import atomic_write_json, read_json, resolve_within
from backend.ignored_errors import ignored
from backend.services import vm_guest, vm_host, vm_store
from backend.services.vm_engine import QmpEngine
from backend.settings import test_mode
from backend.state import Z_STATE, add_event, event_text

VMS_LOCK = threading.RLock()  # one writer of the machine list at a time (SET-07)
SHUTDOWN_GRACE = 120  # seconds a machine gets to shut down before "Turn off now" is offered
ALIVE_STATES = ("running", "paused", "shutting_down")
TEST_PID = 99999  # the stand-in machine of the tests


def locked(fn):
    """For the short routes that read the list, change it and write it back."""

    @functools.wraps(fn)
    def inner(*args, **kwargs):
        with VMS_LOCK:
            return fn(*args, **kwargs)

    return inner


def _pid_is_machine(pid: int, vm_id: str) -> bool:
    """True when that process is this machine's engine. A number left in a file by an earlier run
    of Kiboto can belong to any process by now: trusting it showed a machine as running with
    nothing behind it, kept it out of the automatic start, and let Stop or Delete signal an
    unrelated process (SET-07)."""
    if test_mode() and pid == TEST_PID:
        return True
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return _qmp_socket_path(vm_id).encode() in f.read()
    except OSError:
        return False


def _is_qemu_process_alive(vm_id: str) -> bool:
    """Checks whether the QEMU process for the specified VM is currently alive."""
    entry = vm_store._RUNNING_QEMU_PROCS.get(vm_id)
    if entry:
        proc = entry.get("proc")
        if proc:
            if proc.poll() is None:
                return True
            vm_store._RUNNING_QEMU_PROCS.pop(vm_id, None)
            return False
        pid = entry.get("pid")
        if pid:
            if _pid_is_machine(pid, vm_id):
                return True
            vm_store._RUNNING_QEMU_PROCS.pop(vm_id, None)
            return False

    pid_file = os.path.join(DATA_DIR, "vms", vm_id, "qemu.pid")
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            pid = 0
        if pid and _pid_is_machine(pid, vm_id):
            return True
        try:
            os.remove(pid_file)
        except OSError:
            pass
    return False


_QMP_EVENT_LOG = {
    "SHUTDOWN": ("info", "VM Shut Down", "VM '{name}' shut down ({reason}).", "vm_guest_shutdown"),
    "RESET": ("info", "VM Reset", "VM '{name}' was reset.", "vm_reset"),
    "GUEST_PANICKED": (
        "warning",
        "VM Guest Crashed",
        "The guest OS in VM '{name}' crashed (kernel panic or BSOD).",
        "vm_guest_crashed",
    ),
}


def _on_qmp_event(vm_id: str, event: str, data: dict[str, Any]) -> None:
    """Logs notable QEMU events to the system event log."""
    spec = _QMP_EVENT_LOG.get(event)
    if not spec:
        return
    if event == "SHUTDOWN" and not data.get("guest", False):
        return  # host-initiated stops are already logged by the action that caused them
    name = next((v.get("name") for v in _load_vms() if v.get("id") == vm_id), None) or vm_id
    level, title, message, key = spec
    reason = str(data.get("reason") or "guest")
    add_event(level, title, message.format(name=name, reason=reason), event_text(key, name=name, reason=reason))


def is_machine_running(vm_id: str) -> bool:
    """True while the machine's process lives (running or paused)."""
    return _is_qemu_process_alive(vm_id)


def _qmp_socket_path(vm_id: str) -> str:
    return f"/tmp/{vm_id}-qmp.sock"


_QMP_ENGINE = QmpEngine(_qmp_socket_path, on_event=_on_qmp_event)


def _qmp_command(
    vm_id: str,
    command: str,
    arguments: dict[str, Any] | None = None,
    timeout: float = 2.5,
) -> dict[str, Any]:
    """
    Executes a QMP (QEMU Machine Protocol) command over the VM's persistent
    monitor connection (backend/services/vm_engine.py). Returns QEMU's reply,
    {"return": ...} or {"error": ...}.
    """
    return _QMP_ENGINE.execute(vm_id, command, arguments, timeout)


def _drain_stderr(proc: subprocess.Popen, log_path: str, err_log_path: str, vm_id: str):
    """Background daemon thread to drain QEMU stderr, prevent pipe stall, and log unexpected termination."""
    try:
        if not proc or not proc.stderr:
            return
        with open(log_path, "a", encoding="utf-8") as lf:
            for line in iter(proc.stderr.readline, b""):
                text = line.decode("utf-8", errors="replace")
                lf.write(text)
                lf.flush()
        proc.wait()
        rc = proc.returncode
        if rc not in (0, None, -signal.SIGTERM, -signal.SIGKILL):
            err_msg = f"QEMU process exited abnormally with return code {rc}."
            logger.warning(f"[VM-{vm_id}] {err_msg}")
            with open(err_log_path, "w", encoding="utf-8") as ef:
                ef.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_msg}\n")
            vm_store._LAST_QEMU_ERRORS[vm_id] = err_msg
    except Exception:
        ignored("backend.api.vms._drain_stderr")


def _reconcile_vm_states(vms: list[dict[str, Any]]) -> bool:
    """
    Reconciles in-memory/persisted VM state against actual live QEMU process execution.
    Cleans up phantom 'running' states and captures last recorded errors.
    Returns True if any VM was mutated and requires persistence.
    """
    changed = False
    for vm in vms:
        vm_id = vm.get("id")
        if not vm_id:
            continue
        current_state = vm.get("state", "stopped")
        is_alive = _is_qemu_process_alive(vm_id)

        # Check for recorded error logs
        vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
        err_log = os.path.join(vm_dir, "qemu_last_error.log")
        if os.path.exists(err_log):
            try:
                with open(err_log, encoding="utf-8", errors="replace") as f:
                    content = f.read().strip()
                    if content:
                        vm["last_error"] = content
            except OSError:
                pass

        if current_state in ALIVE_STATES and not is_alive:
            logger.info(
                "[VM-Reconcile] VM '%s' (%s) was marked '%s' but no live process exists. Reconciling to 'stopped'.",
                vm.get("name"),
                vm_id,
                current_state,
            )
            vm["state"] = "stopped"
            vm["uptime_seconds"] = 0
            vm.pop("shutdown_asked_at", None)
            # not on this thread: the monitor's own thread reads the list too, and would wait for itself
            threading.Thread(target=_forget_process, args=(vm_id,), daemon=True).start()
            changed = True
        elif current_state == "stopped" and is_alive:
            vm["state"] = "running"
            changed = True

        if vm.get("state") == "running" and vm_id in vm_store._RUNNING_QEMU_PROCS:
            started = vm_store._RUNNING_QEMU_PROCS[vm_id].get("started_at")
            if started:
                vm["uptime_seconds"] = max(1, int(time.time() - started))

        if vm.get("state") == "shutting_down":
            waited = max(0, int(time.time() - float(vm.get("shutdown_asked_at") or time.time())))
            vm["shutdown_waited_seconds"] = waited
            vm["turn_off_offered"] = waited >= SHUTDOWN_GRACE
        else:
            vm.pop("shutdown_waited_seconds", None)
            vm.pop("turn_off_offered", None)

    return changed


def _load_vms() -> list[dict[str, Any]]:
    """Loads configured virtual machines from persistent JSON storage with live state reconciliation."""
    with VMS_LOCK:
        vms = read_json(vm_store.VMS_CONFIG_FILE, default=None)
        if vms is None:
            default_vms: list[dict[str, Any]] = []
            atomic_write_json(vm_store.VMS_CONFIG_FILE, default_vms)
            return default_vms

        if _reconcile_vm_states(vms):
            _save_vms(vms)

        return vms


def _save_vms(vms: list[dict[str, Any]]) -> None:
    with VMS_LOCK:
        atomic_write_json(vm_store.VMS_CONFIG_FILE, vms)


def save_fields(vm_id: str, fields: dict[str, Any], drop: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Writes some fields of one machine into the list as it is now, and returns the machine.

    An action used to hold a copy of the whole list for seconds (a start, a shutdown, a resize) and
    write it back over whatever had changed meanwhile: an edit, a new machine, another machine's
    state (SET-07)."""
    with VMS_LOCK:
        vms = read_json(vm_store.VMS_CONFIG_FILE, default=None) or []
        vm = next((v for v in vms if v.get("id") == vm_id), None)
        if vm is None:
            return None
        vm.update(fields)
        for key in drop:
            vm.pop(key, None)
        _save_vms(vms)
        return vm


def _get_qemu_vnc_port(vms: list[dict[str, Any]], vm_id: str) -> int:
    """The port a machine's screen listens on. It belongs to the machine and is stored with it.

    It used to be worked out from the machine's place in the list on every use (SET-03). After one
    machine was deleted, the others moved up: their windows then opened the screen, keyboard and
    mouse of the machine that had held that place, and a machine started afterwards was given a port
    a running one still held."""
    idx = next((i for i, v in enumerate(vms) if v.get("id") == vm_id), None)
    if idx is None:
        return 5901
    target = vms[idx]
    stored = target.get("vnc_port")
    if isinstance(stored, int) and 5900 < stored < 65536:
        return stored
    running = vm_store._RUNNING_QEMU_PROCS
    taken = {v.get("vnc_port") for v in vms if v.get("id") != vm_id}
    taken |= {(p or {}).get("vnc_port") for k, p in running.items() if k != vm_id}
    # first the port it runs on now, then the one its place gave it until today, then the next free
    wanted = [(running.get(vm_id) or {}).get("vnc_port"), 5900 + idx + 1]
    port = next((p for p in wanted if isinstance(p, int) and p not in taken), None)
    if port is None:
        port = next(p for p in range(5901, 65536) if p not in taken)
    target["vnc_port"] = port
    _save_vms(vms)
    return port


def _prepare_vtpm(vm_id: str, vm_dir: str, wait_secs: float = 3.0) -> list[str]:
    """Starts a swtpm TPM 2.0 emulator for the VM and returns the QEMU args that attach it.

    Waits for swtpm to create its control socket instead of a fixed sleep, so
    QEMU never races a slow start. Returns [] (VM boots without a TPM) when
    swtpm is missing, fails to start, or does not come up in time.
    """
    swtpm_bin = vm_host._swtpm_binary()
    if not swtpm_bin:
        logger.warning("[VM-%s] swtpm binary not found on host; vTPM 2.0 cannot be initialized.", vm_id)
        return []

    tpm_dir = os.path.join(vm_dir, "tpm")
    os.makedirs(tpm_dir, exist_ok=True)
    tpm_sock = os.path.join(tpm_dir, "swtpm.sock")
    if os.path.exists(tpm_sock):
        try:
            os.remove(tpm_sock)
        except OSError:
            pass

    swtpm_cmd = [
        swtpm_bin,
        "socket",
        "--tpmstate",
        f"dir={tpm_dir}",
        "--ctrl",
        f"type=unixio,path={tpm_sock}",
        "--tpm2",
        "--terminate",
    ]
    try:
        proc = subprocess.Popen(swtpm_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as ex:
        logger.warning("[VM-%s] Failed to spawn swtpm daemon: %s", vm_id, ex)
        return []

    deadline = time.monotonic() + wait_secs
    while not os.path.exists(tpm_sock):
        if proc.poll() is not None:
            logger.warning("[VM-%s] swtpm exited early (code %s); booting without vTPM.", vm_id, proc.returncode)
            return []
        if time.monotonic() >= deadline:
            logger.warning("[VM-%s] swtpm socket did not appear within %.0fs; booting without vTPM.", vm_id, wait_secs)
            try:
                proc.kill()
            except Exception:
                ignored("backend.api.vms._prepare_vtpm")
            return []
        time.sleep(0.05)

    logger.info("[VM-%s] Spawned swtpm vTPM 2.0 daemon on %s", vm_id, tpm_sock)
    return [
        "-chardev",
        f"socket,id=chrtpm,path={tpm_sock}",
        "-tpmdev",
        "emulator,id=tpm0,chardev=chrtpm",
        "-device",
        "tpm-tis,tpmdev=tpm0",
    ]


def share_is_read_only(share: dict[str, Any]) -> bool:
    """The create form saves the choice as mode "ro", the edit form as readonly true. Only the
    first was read, so a folder marked read-only was writable after the first edit (SET-07)."""
    return str(share.get("mode") or "rw") == "ro" or share.get("readonly") is True


def extra_disk_path(vm_dir: str, sdisk: dict[str, Any], idx: int) -> str:
    """The file of an extra disk that has none yet. One left without a name was called "disk", which
    is the system disk's own file: the machine then had its system disk attached twice."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(sdisk.get("name") or "")).strip("_")
    if not name or name == "disk":
        name = f"extra_disk_{idx + 1}"
    return os.path.join(vm_dir, f"{name}.qcow2")


def _start_qemu(target_vm: dict[str, Any], vnc_port: int) -> tuple[bool, str | None]:
    vm_id = target_vm["id"]
    if _is_qemu_process_alive(vm_id):
        return True, None

    vm_dir = os.path.join(DATA_DIR, "vms", vm_id)
    os.makedirs(vm_dir, exist_ok=True)
    err_log_path = os.path.join(vm_dir, "qemu_last_error.log")
    full_log_path = os.path.join(vm_dir, "qemu.log")

    # Graceful test mock fallback when running unit tests
    if test_mode():
        logger.info("Test environment: mocking QEMU start for VM '%s'.", target_vm["name"])
        vm_store._RUNNING_QEMU_PROCS[vm_id] = {
            "proc": None,
            "pid": 99999,
            "vnc_port": vnc_port,
            "started_at": time.time(),
        }
        with open(os.path.join(vm_dir, "qemu.pid"), "w") as f:
            f.write("99999")
        return True, None

    pci_problem = vm_host._pci_passthrough_problem(target_vm)
    if pci_problem:
        logger.error("[VM-%s] %s", vm_id, pci_problem)
        return False, pci_problem

    qemu_bin = shutil.which("qemu-system-x86_64") or "/usr/bin/qemu-system-x86_64"
    if not os.path.exists(qemu_bin) and not shutil.which(qemu_bin):
        err_msg = (
            "This is the core Kiboto image, which has no virtual machine support. Switch to the full image (:latest)."
            if vm_host._image_variant() == "core"
            else "qemu-system-x86_64 binary not found on host. Ensure qemu-system-x86 is installed."
        )
        logger.error("[VM-%s] %s", vm_id, err_msg)
        with open(err_log_path, "w", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_msg}\n")
        target_vm["last_error"] = err_msg
        vm_store._LAST_QEMU_ERRORS[vm_id] = err_msg
        return False, err_msg

    disk_path = target_vm.get("disk_path") or os.path.join(vm_dir, "disk.qcow2")
    target_vm["disk_path"] = disk_path
    disk_problem = vm_store._primary_disk_problem(target_vm, disk_path)
    if disk_problem:
        logger.error("[VM-%s] %s", vm_id, disk_problem)
        target_vm["last_error"] = disk_problem
        vm_store._LAST_QEMU_ERRORS[vm_id] = disk_problem
        return False, disk_problem

    if not os.path.exists(disk_path):
        size_gb = int(target_vm.get("disk_size_gb", 32) or 32)
        qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
        try:
            subprocess.run(
                [qemu_img, "create", "-f", "qcow2", disk_path, f"{size_gb}G"],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except Exception as e:
            err_msg = f"Failed to initialize primary disk: {e}"
            logger.error("[VM-%s] %s", vm_id, err_msg)
            with open(err_log_path, "w", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {err_msg}\n")
            target_vm["last_error"] = err_msg
            vm_store._LAST_QEMU_ERRORS[vm_id] = err_msg
            return False, err_msg

    has_kvm = vm_host._can_use_kvm()
    target_vm["kvm_accelerated"] = has_kvm
    target_vm["acceleration"] = "kvm" if has_kvm else "tcg"

    ram_mb = int(float(target_vm.get("ram_gb", 2.0)) * 1024)
    vcpus = str(target_vm.get("vcpus", 2))
    vnc_display = max(1, vnc_port - 5900)

    sock_path = f"/tmp/{vm_id}-serial.sock"
    qmp_path = f"/tmp/{vm_id}-qmp.sock"
    qga_path = vm_guest._qga_socket_path(vm_id)
    for s in (sock_path, qmp_path, qga_path):
        if os.path.exists(s):
            try:
                os.remove(s)
            except OSError:
                pass

    # Network Bridge inspection vs user-mode SLIRP fallback
    bridge_name = target_vm.get("bridge", "br0")
    tun_writable = os.path.exists("/dev/net/tun") and os.access("/dev/net/tun", os.R_OK | os.W_OK)
    bridge_helper = shutil.which("qemu-bridge-helper") or "/usr/lib/qemu/qemu-bridge-helper"
    has_bridge_helper = os.path.exists(bridge_helper) and os.access(bridge_helper, os.X_OK)
    active_bridges = vm_host.scan_bridges()
    use_bridge = (bridge_name in active_bridges) and tun_writable and has_bridge_helper

    # No port of the NAS leads into the machine. One used to be opened on every network of the NAS
    # for each machine that is not on the home network, without saying so (SET-07).
    target_vm.pop("ssh_port", None)
    mac = target_vm.get("mac") or "52:54:00:12:34:56"

    def _build_cmd(force_slirp: bool = False) -> list[str]:
        vcpus_val = target_vm.get("vcpus", 2)
        sockets = target_vm.get("sockets")
        cores = target_vm.get("cores")
        threads = target_vm.get("threads")
        if sockets and cores:
            smp_parts = [f"{vcpus_val}", f"sockets={sockets}", f"cores={cores}"]
            if threads:
                smp_parts.append(f"threads={threads}")
            smp_str = ",".join(smp_parts)
        else:
            smp_str = str(vcpus_val)

        c = [
            qemu_bin,
            "-name",
            target_vm["name"],
            "-m",
            str(ram_mb),
            "-smp",
            smp_str,
        ]
        if has_kvm:
            c.extend(["-enable-kvm", "-cpu", "host"])
        else:
            c.extend(["-accel", "tcg", "-cpu", "qemu64"])

        firmware = target_vm.get("firmware", "seabios")
        if firmware == "uefi":
            code_path, vars_path = vm_host._find_ovmf_firmware()
            if code_path:
                if vars_path:
                    vm_vars = os.path.join(vm_dir, "OVMF_VARS.fd")
                    if not os.path.exists(vm_vars):
                        try:
                            shutil.copyfile(vars_path, vm_vars)
                        except Exception as e:
                            logger.warning(f"[VM-{vm_id}] Could not copy OVMF_VARS template: {e}")
                    if os.path.exists(vm_vars):
                        c.extend(
                            [
                                "-drive",
                                f"if=pflash,format=raw,readonly=on,file={code_path}",
                                "-drive",
                                f"if=pflash,format=raw,file={vm_vars}",
                            ]
                        )
                    else:
                        c.extend(["-drive", f"if=pflash,format=raw,readonly=on,file={code_path}"])
                else:
                    c.extend(["-drive", f"if=pflash,format=raw,readonly=on,file={code_path}"])

        disk_bus = target_vm.get("disk_bus", "virtio")
        disk_fmt = target_vm.get("disk_format") or ("raw" if disk_path.endswith((".raw", ".img")) else "qcow2")
        if os.path.exists(disk_path):
            c.extend(["-drive", f"file={disk_path},if={disk_bus},format={disk_fmt},id=drive0"])

        iso_path = (
            vm_store._confined(target_vm.get("iso_path"), vm_store._vm_iso_roots(), "file")
            if target_vm.get("iso_path")
            else None
        )
        if target_vm.get("iso_path") and not iso_path:
            logger.warning(f"[VM-{vm_id}] ISO path is outside the ISO/storage folders; not attaching it.")
        boot_order = target_vm.get("boot_order", "iso" if iso_path else "disk")
        if iso_path and os.path.exists(iso_path):
            if boot_order == "disk":
                c.extend(["-cdrom", iso_path, "-boot", "order=cd,menu=on"])
            else:
                c.extend(["-cdrom", iso_path, "-boot", "order=dc,menu=on"])
        else:
            c.extend(["-boot", "order=c"])

        # Video adapter & graphical display
        video_adapter = target_vm.get("video_adapter") or target_vm.get("display_adapter") or "virtio-gpu"
        if video_adapter == "none":
            c.extend(["-vga", "none"])
        elif video_adapter == "qxl":
            c.extend(["-vga", "qxl"])
        elif video_adapter == "vga":
            c.extend(["-vga", "std"])
        else:
            c.extend(["-vga", "virtio"])

        # Display and Console sockets
        c.extend(["-vnc", f"127.0.0.1:{vnc_display}", "-display", "none"])
        c.extend(["-chardev", f"socket,id=serial0,path={sock_path},server=on,wait=off", "-serial", "chardev:serial0"])
        c.extend(
            ["-chardev", f"socket,id=qmp0,path={qmp_path},server=on,wait=off", "-mon", "chardev=qmp0,mode=control"]
        )
        # QEMU Guest Agent channel: lets qemu-guest-agent in the VM report its IPs.
        c.extend(
            [
                "-chardev",
                f"socket,id=qga0,path={qga_path},server=on,wait=off",
                "-device",
                "virtio-serial-pci,id=qga-serial",
                "-device",
                "virtserialport,bus=qga-serial.0,chardev=qga0,name=org.qemu.guest_agent.0",
            ]
        )

        # Network interface configuration
        if use_bridge and not force_slirp:
            target_vm["network_mode"] = "bridge"
            target_vm["network_note"] = f"Bridged to {bridge_name}"
            c.extend(
                [
                    "-netdev",
                    f"bridge,id=net0,br={bridge_name},helper={bridge_helper}",
                    "-device",
                    f"virtio-net-pci,netdev=net0,mac={mac}",
                ]
            )
        else:
            target_vm["network_mode"] = "slirp"
            target_vm["network_note"] = "Private network: the machine reaches out, nothing reaches it"
            c.extend(
                [
                    "-netdev",
                    "user,id=net0",
                    "-device",
                    f"virtio-net-pci,netdev=net0,mac={mac}",
                ]
            )

        for idx_s, share in enumerate(target_vm.get("host_shares", [])):
            hp = share.get("host_path")
            raw_tag = str(share.get("mount_tag") or f"share{idx_s}")
            tag = re.sub(r"[^a-zA-Z0-9_-]", "_", raw_tag)
            ro_flag = "readonly=on" if share_is_read_only(share) else "readonly=off"
            if hp and os.path.exists(hp):
                if "," in hp or "\n" in hp or "\r" in hp:
                    logger.warning(f"[VMs] Host share path contains prohibited characters: {hp}")
                    continue
                # Confinement: storage folders only, never the app's data folder (SEC-07)
                safe_hp = vm_store._confined(hp, vm_store._vm_share_roots(), "dir")
                if not safe_hp:
                    logger.warning(f"[VMs] Host share path '{hp}' is outside permitted storage roots; omitting.")
                    continue
                c.extend(
                    [
                        "-fsdev",
                        f"local,id=fsdev{idx_s},path={safe_hp},security_model=none,{ro_flag}",
                        "-device",
                        f"virtio-9p-pci,fsdev=fsdev{idx_s},mount_tag={tag}",
                    ]
                )

        # Virtual TPM 2.0 (swtpm daemon socket) for Windows 11 and BitLocker readiness
        if target_vm.get("tpm_enabled"):
            c.extend(_prepare_vtpm(vm_id, vm_dir))

        for idx_d, sdisk in enumerate(target_vm.get("secondary_disks", [])):
            sd_path = sdisk.get("path")
            if not sd_path:
                sd_path = extra_disk_path(vm_dir, sdisk, idx_d)
                sdisk["path"] = sd_path
            if not vm_store._confined(sd_path, vm_store._vm_disk_roots(), "file"):
                logger.warning(f"[VM-{vm_id}] Secondary disk {idx_d + 1} is outside the VM/storage folders; skipping.")
                continue
            if not os.path.exists(sd_path):
                try:
                    qemu_img = shutil.which("qemu-img") or "/usr/bin/qemu-img"
                    subprocess.run(
                        [qemu_img, "create", "-f", "qcow2", sd_path, f"{sdisk.get('size_gb', 20)}G"],
                        check=True,
                        timeout=120,
                    )
                except Exception:
                    ignored("backend.api.vms._start_qemu._build_cmd")
            safe_sd = vm_store._confined(sd_path, vm_store._vm_disk_roots(), "file")
            sbus = str(sdisk.get("bus", "virtio"))
            sfmt = str(sdisk.get("format") or ("raw" if str(sd_path).endswith((".raw", ".img")) else "qcow2"))
            if not safe_sd or sbus not in vm_store._DISK_BUSES or sfmt not in vm_store._DISK_FORMATS:
                logger.warning(f"[VM-{vm_id}] Secondary disk {idx_d + 1} has unsafe settings; not attaching it.")
                continue
            sd_path = safe_sd
            if os.path.exists(sd_path):
                c.extend(["-drive", f"file={sd_path},if={sbus},format={sfmt},id=sdisk{idx_d}"])

        # Host USB Passthrough Devices
        usb_devices = target_vm.get("usb_passthrough", [])
        if usb_devices:
            if not os.path.exists("/dev/bus/usb") and os.path.exists("/host/dev/bus/usb"):
                try:
                    os.makedirs("/dev/bus", exist_ok=True)
                    os.symlink("/host/dev/bus/usb", "/dev/bus/usb")
                except OSError:
                    pass
            c.extend(["-device", "qemu-xhci,id=xhci"])
            for idx_u, udev in enumerate(usb_devices):
                raw_vid = str(udev.get("vendor_id", "")).strip().lower().replace("0x", "")
                raw_pid = str(udev.get("product_id", "")).strip().lower().replace("0x", "")
                if (
                    raw_vid
                    and raw_pid
                    and re.match(r"^[0-9a-fA-F]{1,4}$", raw_vid)
                    and re.match(r"^[0-9a-fA-F]{1,4}$", raw_pid)
                ):
                    c.extend(
                        [
                            "-device",
                            f"usb-host,vendorid=0x{raw_vid},productid=0x{raw_pid},id=usb_pass_{idx_u}",
                        ]
                    )

        # Host PCI / GPU Passthrough (VFIO-PCI); readiness is checked before launch.
        for idx_p, pdev in enumerate(vm_host._sanitize_pci_list(target_vm.get("pci_passthrough"))):
            c.extend(["-device", f"vfio-pci,host={pdev['slot']},id=vfio_pass_{idx_p}"])

        affinity = target_vm.get("cpu_affinity")
        if affinity and isinstance(affinity, list) and len(affinity) > 0:
            aff_str = ",".join(str(int(x)) for x in affinity)
            taskset_bin = shutil.which("taskset") or "/usr/bin/taskset"
            if os.path.exists(taskset_bin):
                c = [taskset_bin, "-c", aff_str] + c

        return c

    cmd = _build_cmd(force_slirp=False)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(0.4)
        if proc.poll() is not None:
            _, err = proc.communicate()
            err_msg = err.decode("utf-8", errors="replace").strip() if err else "process exited immediately"

            # Fallback to SLIRP if bridge failed
            if use_bridge:
                logger.warning(
                    "Bridge network failed for VM '%s'. Retrying with user-mode SLIRP: %s", target_vm["name"], err_msg
                )
                cmd = _build_cmd(force_slirp=True)
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                time.sleep(0.4)
                if proc.poll() is not None:
                    _, err2 = proc.communicate()
                    err_msg = err2.decode("utf-8", errors="replace").strip() if err2 else err_msg

            if proc.poll() is not None:
                logger.error("QEMU failed to start for VM '%s': %s", target_vm["name"], err_msg)
                with open(err_log_path, "w", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] QEMU start failure:\n{err_msg}\n")
                target_vm["last_error"] = err_msg
                vm_store._LAST_QEMU_ERRORS[vm_id] = err_msg
                return False, err_msg

        vm_store._RUNNING_QEMU_PROCS[vm_id] = {
            "proc": proc,
            "pid": proc.pid,
            "vnc_port": vnc_port,
            "started_at": time.time(),
        }
        vm_store._LAST_QEMU_ERRORS.pop(vm_id, None)
        with open(os.path.join(vm_dir, "qemu.pid"), "w") as f:
            f.write(str(proc.pid))

        if os.path.exists(err_log_path):
            try:
                os.remove(err_log_path)
            except OSError:
                pass
        target_vm["last_error"] = None

        t = threading.Thread(target=_drain_stderr, args=(proc, full_log_path, err_log_path, vm_id), daemon=True)
        t.start()
        _QMP_ENGINE.watch(vm_id)

        return True, None
    except Exception as e:
        err_msg = str(e)
        logger.error("Exception spawning QEMU for VM '%s': %s", target_vm["name"], err_msg)
        with open(err_log_path, "w", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Exception starting QEMU: {err_msg}\n")
        target_vm["last_error"] = err_msg
        vm_store._LAST_QEMU_ERRORS[vm_id] = err_msg
        return False, err_msg


def _sync_cleanup_qemu_process(vm_id: str, force: bool = False):
    """Terminates or kills the QEMU process and removes temporary sockets and PID files."""
    entry = vm_store._RUNNING_QEMU_PROCS.pop(vm_id, None)
    proc = entry.get("proc") if entry else None
    pid = entry.get("pid") if entry else None

    if not pid:
        pid_file = os.path.join(DATA_DIR, "vms", vm_id, "qemu.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    pid = int(f.read().strip())
            except Exception:
                ignored("backend.api.vms._sync_cleanup_qemu_process")

    if proc and proc.poll() is None:
        if force:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()

    if pid and pid != TEST_PID and _pid_is_machine(pid, vm_id):
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.kill(pid, sig)
        except OSError:
            pass

    pid_file = os.path.join(DATA_DIR, "vms", vm_id, "qemu.pid")
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except OSError:
            pass

    _forget_process(vm_id)


def _forget_process(vm_id: str) -> None:
    """What a machine that is off leaves behind: the monitor connection and its sockets."""
    vm_guest._forget_vm_ip(vm_id)
    _QMP_ENGINE.close(vm_id)
    for s in (f"/tmp/{vm_id}-serial.sock", f"/tmp/{vm_id}-qmp.sock", vm_guest._qga_socket_path(vm_id)):
        if os.path.exists(s):
            try:
                os.remove(s)
            except OSError:
                pass


def ask_to_shut_down(vm_id: str) -> bool:
    """Presses the machine's power button. True when the machine took the request. It never ends
    the process: what happens next is up to the system inside. "Shut down" used to wait two seconds
    and then kill, and killed at once when the request was not acknowledged (SET-07)."""
    if "return" in _qmp_command(vm_id, "system_powerdown", None, 1.5):
        return True
    entry = vm_store._RUNNING_QEMU_PROCS.get(vm_id) or {}
    if test_mode() and entry.get("pid") == TEST_PID and not entry.get("proc"):
        _sync_cleanup_qemu_process(vm_id)  # the stand-in machine of the tests has no monitor: it is off at once
        return True
    return False


async def async_stop_qemu(vm_id: str, force: bool = False):
    """Asynchronously stops the QEMU process without blocking the FastAPI event loop."""
    if not force:
        qmp_res = await asyncio.to_thread(_qmp_command, vm_id, "system_powerdown", None, 1.5)
        if "return" in qmp_res:
            logger.info("[VM-%s] ACPI powerdown signal sent via QMP.", vm_id)
            for _ in range(20):
                await asyncio.sleep(0.1)
                is_alive = await asyncio.to_thread(_is_qemu_process_alive, vm_id)
                if not is_alive:
                    break

    await asyncio.to_thread(_sync_cleanup_qemu_process, vm_id, force=force)


def shut_down_all(
    wait_secs: float = SHUTDOWN_GRACE, come_back: bool = True, turn_off: bool = True
) -> dict[str, list[str]]:
    """Asks every running machine to shut down and waits for them, before Kiboto restarts, updates
    or turns the NAS off. Nothing did: the machines were killed with Kiboto, and only those set to
    start with the NAS came back (SET-07).

    A machine still running after the wait is turned off, which is written to Activity; with
    turn_off false it is left to whoever ends Kiboto. With come_back the machines are started again
    at Kiboto's next start. The answer names the machines that shut down and those turned off."""
    asked = []
    for vm in _load_vms():
        vm_id = vm.get("id")
        if not vm_id or vm.get("state") not in ALIVE_STATES or not _is_qemu_process_alive(vm_id):
            continue
        if vm.get("state") == "paused":
            _qmp_command(vm_id, "cont")  # a frozen machine hears nothing
        took = ask_to_shut_down(vm_id)
        fields: dict[str, Any] = {
            "state": "shutting_down",
            "shutdown_asked_at": vm.get("shutdown_asked_at") or time.time(),
        }
        if come_back:
            fields["start_again"] = True
        save_fields(vm_id, fields)
        asked.append({"id": vm_id, "name": vm.get("name") or vm_id, "took": took})
    if not asked:
        return {"shut_down": [], "turned_off": []}

    deadline = time.monotonic() + wait_secs
    # a machine that did not take the request will not shut down by waiting
    while time.monotonic() < deadline and any(m["took"] and _is_qemu_process_alive(m["id"]) for m in asked):
        time.sleep(1.0)

    done: dict[str, list[str]] = {"shut_down": [], "turned_off": []}
    for m in asked:
        if _is_qemu_process_alive(m["id"]):
            if not turn_off:
                continue
            _sync_cleanup_qemu_process(m["id"], force=True)
            done["turned_off"].append(m["name"])
            add_event(
                "warning",
                "VM Turned Off",
                f"VM '{m['name']}' did not shut down within {int(wait_secs)} seconds and was turned off.",
                event_text("vm_turned_off", name=m["name"], secs=int(wait_secs)),
            )
        else:
            _forget_process(m["id"])
            done["shut_down"].append(m["name"])
        save_fields(m["id"], {"state": "stopped", "uptime_seconds": 0}, ("shutdown_asked_at",))
    logger.info("[VMs] before Kiboto ends: shut down %s, turned off %s", done["shut_down"], done["turned_off"])
    return done


def machines_first(come_back: bool = True) -> None:
    """shut_down_all() for the callers that go on whatever happens: an update, a restart, the
    power buttons."""
    try:
        shut_down_all(come_back=come_back)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("[VMs] could not shut the virtual machines down first: %s", e)
