"""B15 PERF-31: no default memory limit; a warning when the app's own memory grows too large."""

import pytest

from backend.services import alert_rules


def _proc(root, pid, cmd, rss_kb):
    d = root / str(pid)
    d.mkdir()
    (d / "cmdline").write_bytes(cmd.replace(" ", "\0").encode())
    (d / "status").write_text(f"Name:\tx\nVmRSS:\t{rss_kb} kB\n")


def test_the_apps_memory_leaves_out_virtual_machines(tmp_path):
    _proc(tmp_path, 1, "python3 -m backend.main", 200 * 1024)
    _proc(tmp_path, 2, "/usr/bin/rclone serve webdav", 30 * 1024)
    _proc(tmp_path, 3, "/usr/bin/qemu-system-x86_64 -m 8192", 8 * 1024 * 1024)
    (tmp_path / "self").mkdir()
    (tmp_path / "9").mkdir()  # gone while reading
    assert alert_rules.app_memory_mb(str(tmp_path)) == 230


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr("backend.services.notifications.send_notification", lambda n: sent.append(n))
    monkeypatch.setattr(alert_rules, "add_event", lambda level, title, msg: None)
    monkeypatch.setattr("backend.config.APP_MEMORY_WARN_MB", 1000)
    alert_rules.reset_failsafe_state()
    yield sent
    alert_rules.reset_failsafe_state()


def test_over_the_level_warns_once_a_minute_at_most_and_clears_below_ninety_percent(alerts):
    alert_rules.check_app_memory(1000.0, measure=lambda: 1200.0)
    assert "app_memory" in alert_rules._active_alerts and len(alerts) == 1
    alert_rules.check_app_memory(1030.0, measure=lambda: 100.0)  # within the minute: not measured
    assert "app_memory" in alert_rules._active_alerts
    alert_rules.check_app_memory(1070.0, measure=lambda: 950.0)  # under the level but not 90 %: stays
    assert "app_memory" in alert_rules._active_alerts
    alert_rules.check_app_memory(1140.0, measure=lambda: 850.0)
    assert "app_memory" not in alert_rules._active_alerts


def test_zero_turns_it_off(alerts, monkeypatch):
    monkeypatch.setattr("backend.config.APP_MEMORY_WARN_MB", 0)
    alert_rules.check_app_memory(1000.0, measure=lambda: 99999.0)
    assert not alerts and "app_memory" not in alert_rules._active_alerts


def test_the_check_runs_with_the_other_alerts(alerts, monkeypatch):
    seen = []
    monkeypatch.setattr(alert_rules, "check_app_memory", lambda now: seen.append(now))
    alert_rules.evaluate_system_alerts({}, {})
    assert len(seen) == 1

    def broken(now):
        raise OSError("no /proc")

    monkeypatch.setattr(alert_rules, "check_app_memory", broken)
    alert_rules.evaluate_system_alerts({}, {})  # a failing check never stops the alert rules
