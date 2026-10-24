"""Startup and shutdown: supervised daemons, the newer-database guard, the default password warning,
VM autostart, the fan watchdog, the Docker proxy hand-off, the lifespan and signal handling."""

import asyncio
import os
import time

import pytest

from backend import main
from backend.state import Z_STATE


@pytest.fixture
def quiet(monkeypatch):
    """startup_system with every daemon and device recorded instead of started."""
    rec = {"supervised": [], "threads": [], "atexit": [], "events": [], "started": []}
    # nothing that writes the shared test data folder (encryption, permissions, schema stamps)
    noop = lambda *a, **k: None  # noqa: E731
    for target in (
        "backend.db_schema.stamp_versions",
        "backend.services.data_snapshot.snapshot_if_build_changed",
        "backend.db_crypto.prepare",
        "backend.db_crypto.prepare_in_background",
        "backend.services.security_upgrade.run_once",
        "backend.api.auth.align_admin_password_mirror",
        "backend.services.self_updater.report_last_update_result",
        "backend.secret_box.migrate_plaintext_mfa_secrets",
        "backend.services.data_permissions.harden_data_permissions",
        "backend.main.init_db",
        "backend.main._load_security",
        "backend.main.purge_legacy_session_files",
        "backend.main._load_events",
        "backend.main.read_cpu_util",
    ):
        monkeypatch.setattr(target, noop)
    monkeypatch.setattr("backend.db_schema.check_versions", noop)
    monkeypatch.setattr("backend.services.supervisor.supervise", lambda name, fn: rec["supervised"].append(name))
    monkeypatch.setattr(main, "setup_structured_logging", lambda: None)
    monkeypatch.setattr(main, "read_ip", lambda: "10.0.0.2")
    monkeypatch.setattr(main, "detect_chassis_model", lambda: "d6u")
    monkeypatch.setattr(main, "apply_led_state", lambda cfg: None)
    monkeypatch.setattr(main, "start_backup_scheduler", lambda: rec["started"].append("backup"))
    monkeypatch.setattr("backend.services.scheduler.start_scheduler", lambda: rec["started"].append("scheduler"))
    monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", lambda: rec["started"].append("rag"))
    monkeypatch.setattr(main.get_webdav_engine(), "start_if_enabled", lambda: rec["started"].append("webdav"))
    monkeypatch.setattr(main.atexit, "register", lambda fn: rec["atexit"].append(fn))
    monkeypatch.setattr(main, "add_event", lambda level, title, msg, **k: rec["events"].append(title))

    class Thread:
        def __init__(self, target=None, daemon=None, name=None):
            rec["threads"].append((name, target))

        def start(self):
            pass

    monkeypatch.setattr(main.threading, "Thread", Thread)
    return rec


class TestStartup:
    def test_launches_the_supervised_daemons(self, quiet, monkeypatch):
        monkeypatch.setattr("backend.hardware.fans.is_zettlab_appliance", lambda: True)
        main.startup_system()
        assert {"StatsCollector", "SmartPoller", "ButtonListener", "LcdRenderer", "FanWatchdog"} <= set(
            quiet["supervised"]
        )
        assert {"backup", "scheduler", "rag", "webdav"} <= set(quiet["started"])
        assert "VmAutostart" in [n for n, _ in quiet["threads"]] and quiet["atexit"]

    def test_no_button_listener_on_other_hardware(self, quiet, monkeypatch):
        monkeypatch.setattr("backend.hardware.fans.is_zettlab_appliance", lambda: False)
        main.startup_system()
        assert "ButtonListener" not in quiet["supervised"]

    def test_a_newer_database_stops_the_start(self, quiet, monkeypatch):
        from backend import db_schema

        def newer():
            raise db_schema.NewerDatabaseError("users.db was written by a newer ZettNAS")

        monkeypatch.setattr(db_schema, "check_versions", newer)
        with pytest.raises(SystemExit) as exc:
            main.startup_system()
        assert exc.value.code == 3

    def test_default_password_warning(self, quiet, monkeypatch):
        monkeypatch.setattr(main, "is_using_default_password", lambda: True)
        main.startup_system()
        assert "Default Password In Use" in quiet["events"]

    def test_failing_services_do_not_stop_the_start(self, quiet, monkeypatch):
        def boom():
            raise RuntimeError("down")

        monkeypatch.setattr(main, "start_backup_scheduler", boom)
        monkeypatch.setattr("backend.services.scheduler.start_scheduler", boom)
        monkeypatch.setattr("backend.services.rag_engine.get_rag_engine", boom)
        monkeypatch.setattr(main.get_webdav_engine(), "start_if_enabled", boom)
        main.startup_system()
        assert "StatsCollector" in quiet["supervised"]

    def test_vm_autostart(self, quiet, monkeypatch):
        main.startup_system()
        autostart = dict(quiet["threads"])["VmAutostart"]
        vms = [
            {"id": "a", "name": "A", "autostart": True, "state": "stopped"},
            {"id": "b", "name": "B", "autostart": False, "state": "stopped"},
            {"id": "c", "name": "C", "autostart": True, "state": "stopped"},
        ]
        saved, started = [], []
        from backend.api import vms as vms_api

        monkeypatch.setattr(time, "sleep", lambda s: None)
        monkeypatch.setattr(vms_api, "_load_vms", lambda: vms)
        monkeypatch.setattr(vms_api, "_save_vms", lambda v: saved.append([x["state"] for x in v]))
        monkeypatch.setattr(vms_api, "_is_qemu_process_alive", lambda vm_id: vm_id == "c")
        monkeypatch.setattr(vms_api, "_get_qemu_vnc_port", lambda v, vm_id: 5901)
        monkeypatch.setattr(vms_api, "_start_qemu", lambda vm, port: (started.append(vm["id"]) or True, None))
        autostart()
        assert started == ["a"] and saved == [["running", "stopped", "stopped"]]


class TestFanWatchdog:
    def test_releases_the_fans_when_the_collector_stalls(self, monkeypatch):
        released, events = [], []
        monkeypatch.setattr(main, "failsafe_release_fans", lambda reason, **k: released.append(reason))
        monkeypatch.setattr(main, "add_event", lambda *a, **k: events.append(a[1]))
        monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time() - 3600)
        monkeypatch.setattr(Z_STATE, "fans_locked", False)
        monkeypatch.setattr(Z_STATE, "fans_released", False)
        monkeypatch.setattr(Z_STATE, "shutting_down", False)
        ticks = []

        def sleep(s):
            ticks.append(s)
            if len(ticks) > 1:
                Z_STATE.shutting_down = True

        monkeypatch.setattr(main.time, "sleep", sleep)
        main.fan_watchdog_daemon()
        assert released == ["watchdog"] and events == ["Fan Watchdog Triggered"]

    def test_quiet_while_the_collector_runs(self, monkeypatch):
        released = []
        monkeypatch.setattr(main, "failsafe_release_fans", lambda reason, **k: released.append(reason))
        monkeypatch.setattr(Z_STATE, "collector_heartbeat", time.time())
        monkeypatch.setattr(Z_STATE, "shutting_down", False)

        def sleep(s):
            Z_STATE.shutting_down = True

        monkeypatch.setattr(main.time, "sleep", sleep)
        main.fan_watchdog_daemon()
        assert released == []

    def test_shutdown_fans_never_raises(self, monkeypatch):
        def boom(reason, lock=False):
            raise OSError("pwm gone")

        monkeypatch.setattr(main, "failsafe_release_fans", boom)
        main._shutdown_fans("exit")


class TestDockerProxy:
    def test_points_the_app_at_the_proxy(self, tmp_path, monkeypatch):
        raw = tmp_path / "docker.sock"
        raw.write_text("")
        proxy = tmp_path / "proxy.sock"
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setenv("ZETTNAS_DOCKER_PROXY_SOCK", str(proxy))
        monkeypatch.delenv("ZETTNAS_DOCKER_SOCK", raising=False)
        monkeypatch.setattr("backend.config.RAW_DOCKER_SOCK", str(raw))
        supervised = []

        def supervise(name, fn):
            supervised.append(name)
            proxy.write_text("")  # the proxy comes up

        main._start_docker_proxy(supervise)
        assert supervised == ["DockerProxy"] and os.environ["ZETTNAS_DOCKER_SOCK"] == str(proxy)

    def test_falls_back_when_the_proxy_does_not_start(self, tmp_path, monkeypatch):
        raw = tmp_path / "docker.sock"
        raw.write_text("")
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setenv("ZETTNAS_DOCKER_PROXY_SOCK", str(tmp_path / "never.sock"))
        monkeypatch.delenv("ZETTNAS_DOCKER_SOCK", raising=False)
        monkeypatch.setattr("backend.config.RAW_DOCKER_SOCK", str(raw))
        monkeypatch.setattr(main.time, "sleep", lambda s: None)
        main._start_docker_proxy(lambda name, fn: None)
        assert "ZETTNAS_DOCKER_SOCK" not in os.environ

    def test_off_or_without_docker(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setenv("ZETTNAS_DOCKER_PROXY", "off")
        main._start_docker_proxy(lambda name, fn: called.append(name))
        monkeypatch.delenv("ZETTNAS_DOCKER_PROXY")
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setattr("backend.config.RAW_DOCKER_SOCK", str(tmp_path / "none.sock"))
        main._start_docker_proxy(lambda name, fn: called.append(name))
        assert called == []


def test_lifespan_starts_and_stops_everything(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "startup_system", lambda: calls.append("start"))
    monkeypatch.setattr(main, "close_notification_client", lambda: calls.append("notify"))
    monkeypatch.setattr(main, "stop_backup_scheduler", lambda: calls.append("backup"))
    monkeypatch.setattr("backend.services.scheduler.stop_scheduler", lambda: calls.append("scheduler"))
    monkeypatch.setattr(main.get_webdav_engine(), "stop", lambda: calls.append("webdav"))
    monkeypatch.setattr(main.broadcaster, "shutdown", lambda: calls.append("broadcast"))
    monkeypatch.setattr(main, "_shutdown_fans", lambda reason: calls.append("fans:" + reason))
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    monkeypatch.setattr(Z_STATE, "fans_locked", False)

    async def run():
        async with main.lifespan(main.app):
            calls.append("serving")

    asyncio.run(run())
    assert calls[:2] == ["start", "serving"] and Z_STATE.shutting_down
    assert {"notify", "backup", "scheduler", "webdav", "broadcast", "fans:shutdown"} <= set(calls)


def test_signal_releases_the_fans(monkeypatch):
    released = []
    monkeypatch.setattr(main, "_shutdown_fans", lambda reason: released.append(reason))
    monkeypatch.setattr(Z_STATE, "fans_locked", False)
    monkeypatch.setattr(Z_STATE, "shutting_down", False)
    monkeypatch.setattr(main.uvicorn.Server, "handle_exit", lambda self, sig, frame: None)
    server = main.ZettServer.__new__(main.ZettServer)
    server.handle_exit(15, None)
    assert released == ["signal 15"] and Z_STATE.shutting_down


def test_main_configures_uvicorn(monkeypatch):
    seen = {}
    monkeypatch.setenv("PORT", "9090")
    monkeypatch.setattr(main.ZettServer, "__init__", lambda self, cfg: seen.update(port=cfg.port, host=cfg.host))
    monkeypatch.setattr(main.ZettServer, "run", lambda self: seen.update(ran=True))
    main.main()
    assert seen == {"port": 9090, "host": "0.0.0.0", "ran": True}
