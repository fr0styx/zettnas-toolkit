"""System API: reboot/power-off triggers (the kernel fallback flushes disks first), SMART
self-test routes and the front-panel copy controls."""

import pytest

from backend.api import system as system_api
from backend.state import Z_STATE


@pytest.fixture
def real_power(monkeypatch, tmp_path):
    """Leaves test mode for trigger_power_action, with no real command reachable."""
    monkeypatch.setenv("TESTING", "0")
    monkeypatch.delenv("ZETTNAS_TEST_MODE", raising=False)
    started = []
    monkeypatch.setattr(system_api.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    monkeypatch.setattr(system_api.shutil, "which", lambda name: None)
    monkeypatch.setattr(system_api, "SYSRQ_TRIGGER", str(tmp_path / "sysrq-trigger"))
    monkeypatch.setattr(system_api.time, "sleep", lambda s: None)
    monkeypatch.setattr(system_api.os, "sync", lambda: started.append("sync"))
    # The tests own the command lists: a real /sbin/poweroff on the machine running them
    # (as on CI runners) must not be what they find.
    monkeypatch.setattr(
        system_api, "REBOOT_TRIGGERS", ((str(tmp_path / "host-reboot"),), ("reboot",), ("shutdown", "-r", "now"))
    )
    monkeypatch.setattr(
        system_api, "POWEROFF_TRIGGERS", ((str(tmp_path / "host-powerdown"),), ("poweroff",), ("shutdown", "-h", "now"))
    )
    return started, tmp_path


def test_test_mode_never_powers_anything_off(monkeypatch):
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setattr(system_api.subprocess, "Popen", lambda *a, **k: pytest.fail("ran a power command"))
    assert system_api.trigger_power_action("reboot") is True


def test_host_trigger_script_comes_first(real_power, monkeypatch):
    started, tmp_path = real_power
    script = tmp_path / "powerdown"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    monkeypatch.setattr(system_api, "POWEROFF_TRIGGERS", ((str(script),), ("poweroff",)))
    assert system_api.trigger_power_action("shutdown") is True
    assert started == [[str(script)]]


def test_commands_on_the_path(real_power, monkeypatch):
    started, _ = real_power
    monkeypatch.setattr(system_api.shutil, "which", lambda name: "/usr/sbin/" + name if name == "shutdown" else None)
    assert system_api.trigger_power_action("reboot") is True
    assert started == [["shutdown", "-r", "now"]]


def test_a_failing_command_falls_through_to_the_next(real_power, monkeypatch):
    started, _ = real_power
    monkeypatch.setattr(system_api.shutil, "which", lambda name: "/bin/" + name)

    def popen(cmd, **kw):
        if cmd[0].endswith("host-reboot"):
            raise OSError("not executable")
        started.append(cmd)

    monkeypatch.setattr(system_api.subprocess, "Popen", popen)
    assert system_api.trigger_power_action("reboot") is True
    assert started == [["reboot"]]


@pytest.mark.parametrize(("action", "last_key"), [("reboot", "b"), ("shutdown", "o")])
def test_kernel_fallback_flushes_and_remounts_before_acting(real_power, action, last_key):
    started, tmp_path = real_power
    trigger = tmp_path / "sysrq-trigger"
    written = []

    class Recorder:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def write(self, key):
            written.append(key)

    trigger.write_text("")
    import builtins

    real_open = builtins.open
    system_api.open = lambda path, *a, **k: Recorder() if path == str(trigger) else real_open(path, *a, **k)
    try:
        assert system_api.trigger_power_action(action) is True
    finally:
        del system_api.open
    assert started == ["sync"]
    assert written == ["s", "u", last_key]


def test_nothing_available_reports_failure(real_power):
    started, _ = real_power
    assert system_api.trigger_power_action("reboot") is False
    assert started == []


# ---------------------------------------------------------------------------
# SMART self-tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dev", ["sda;rm", "../sda", "hda", "nvme0", "sdabc"])
def test_smart_routes_refuse_bad_device_names(client, auth_headers, dev):
    assert client.post(
        "/api/disk/smart_test", json={"dev": dev, "test_type": "short"}, headers=auth_headers
    ).status_code in (400, 422)
    assert client.get(f"/api/disk/smart_tests?dev={dev}", headers=auth_headers).status_code == 400


def test_smart_test_accepts_short_device_names(client, auth_headers, monkeypatch):
    seen = []
    monkeypatch.setattr(
        system_api, "run_disk_smart_test", lambda dev, kind: seen.append((dev, kind)) or {"started": True}
    )
    for dev in ("/dev/sdb", "nv1", "nvme0n1"):
        r = client.post("/api/disk/smart_test", json={"dev": dev, "test_type": "short"}, headers=auth_headers)
        assert r.status_code == 200, r.text
    assert [d for d, _ in seen] == ["sdb", "nvme1n1", "nvme0n1"]


def test_smart_test_history(client, auth_headers, monkeypatch):
    import backend.db as db

    monkeypatch.setattr(db, "get_smart_test_history", lambda dev, limit: [{"dev": dev, "limit": limit}])
    monkeypatch.setattr(db, "get_latest_smart_test_result", lambda dev: {"dev": dev, "result": "passed"})
    with Z_STATE.lock:
        Z_STATE.active_smart_tests["sdc"] = {"type": "long", "percent": 40}
    try:
        body = client.get("/api/disk/smart_tests?dev=/dev/sdc&limit=5", headers=auth_headers).json()
    finally:
        with Z_STATE.lock:
            Z_STATE.active_smart_tests.pop("sdc", None)
    assert body["dev"] == "sdc" and body["active_test"]["percent"] == 40
    assert body["latest_report"]["result"] == "passed" and body["history"] == [{"dev": "sdc", "limit": 5}]
    all_disks = client.get("/api/disk/smart_tests", headers=auth_headers).json()
    assert all_disks["latest_report"] is None and all_disks["active_test"] is None


# ---------------------------------------------------------------------------
# Front-panel copy controls
# ---------------------------------------------------------------------------


@pytest.fixture
def copy_state():
    saved = (
        Z_STATE.copy_active,
        Z_STATE.copy_status,
        Z_STATE.copy_paused,
        Z_STATE.copy_abort_flag,
        Z_STATE.copy_overwrite_choice,
    )
    Z_STATE.copy_active, Z_STATE.copy_status, Z_STATE.copy_paused, Z_STATE.copy_abort_flag = False, "idle", False, False
    Z_STATE.copy_confirm_event.clear()
    yield Z_STATE
    (
        Z_STATE.copy_active,
        Z_STATE.copy_status,
        Z_STATE.copy_paused,
        Z_STATE.copy_abort_flag,
        Z_STATE.copy_overwrite_choice,
    ) = saved
    Z_STATE.copy_confirm_event.clear()


def test_copy_pause_resume_confirm_cancel(client, auth_headers, copy_state):
    assert client.post("/api/copy/pause", headers=auth_headers).json() == {"status": "paused"}
    assert copy_state.copy_paused is True
    assert client.post("/api/copy/resume", headers=auth_headers).json() == {"status": "resumed"}
    assert copy_state.copy_paused is False
    r = client.post("/api/copy/confirm", json={"action": "skip"}, headers=auth_headers)
    assert (
        r.status_code == 200 and copy_state.copy_overwrite_choice == "skip" and copy_state.copy_confirm_event.is_set()
    )
    # only the three choices: anything else used to count as overwrite
    assert client.post("/api/copy/confirm", json={"action": "skipp"}, headers=auth_headers).status_code == 422
    assert copy_state.copy_overwrite_choice == "skip"
    copy_state.copy_status = "waiting"
    assert client.post("/api/copy/cancel", headers=auth_headers).json() == {"status": "ok"}
    assert copy_state.copy_abort_flag is True and copy_state.copy_status == "idle"


def test_cancel_during_a_copy_leaves_the_status_to_the_copier(client, auth_headers, copy_state):
    copy_state.copy_active, copy_state.copy_status = True, "copying"
    client.post("/api/copy/cancel", headers=auth_headers)
    assert copy_state.copy_status == "copying" and copy_state.copy_abort_flag is True


def test_copy_start(client, auth_headers, copy_state, monkeypatch):
    started = []
    monkeypatch.setattr(system_api, "_load_buttons", lambda: {"source": "sd", "dest": "/mnt/a", "use_exif": False})
    monkeypatch.setattr(
        system_api.threading,
        "Thread",
        lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(args[0])})(),
    )
    r = client.post("/api/copy/start", json={"source": "usb", "dest": "/mnt/b", "use_exif": True}, headers=auth_headers)
    assert r.json() == {"status": "started"} and copy_state.copy_active is True
    assert started == [{"source": "usb", "dest": "/mnt/b", "use_exif": True}]
    assert client.post("/api/copy/start", headers=auth_headers).status_code == 409


def test_health_reports_the_build(client, monkeypatch):
    monkeypatch.setenv("BUILD_COMMIT", "eb40b52aa1b2c3d4e5f6")
    assert client.get("/api/health").json()["build"] == "eb40b52aa1b2"
    monkeypatch.delenv("BUILD_COMMIT")
    assert client.get("/api/health").json()["build"] == ""
