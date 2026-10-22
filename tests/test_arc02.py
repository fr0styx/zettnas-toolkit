"""ARC-02: background daemons are supervised, and QEMU starts off the event loop."""

import time

from backend.services import supervisor


def _wait(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_crashing_daemon_is_restarted_with_backoff():
    calls = []
    sleeps = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("sensor read failed")

    supervisor.supervise("t-flaky", flaky, _sleep=lambda s: sleeps.append(s))
    assert _wait(lambda: supervisor.daemon_status()["t-flaky"]["state"] == "stopped")
    st = supervisor.daemon_status()["t-flaky"]
    assert len(calls) == 3 and st["restarts"] == 2 and sleeps == [1.0, 2.0]
    assert "sensor read failed" in st["last_error"]


def test_one_shot_is_not_restarted():
    supervisor.supervise("t-once", lambda: (_ for _ in ()).throw(ValueError("x")), restart=False)
    assert _wait(lambda: supervisor.daemon_status()["t-once"]["state"] == "crashed")
    time.sleep(0.05)
    assert supervisor.daemon_status()["t-once"]["restarts"] == 0


def test_console_websocket_starts_qemu_in_a_thread():
    import inspect

    from backend.api import vms

    for fn in (vms.websocket_vm_console, vms.websocket_vm_serial):
        src = inspect.getsource(fn)
        assert "await asyncio.to_thread(_start_qemu" in src and "= _start_qemu(" not in src
