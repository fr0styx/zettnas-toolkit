"""NUX-3: pool alerts, the weekly report and security alerts in the household's language."""

import pytest

from backend.services import notifications, pool_alerts, security_alerts


@pytest.fixture
def german(monkeypatch):
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "de"})


def test_pool_alert_text_in_german_and_english():
    item = {"kind": "pool_degraded", "subject": "tank", "level": "critical"}
    assert pool_alerts._text(item) == (
        "Storage pool tank is degraded",
        "Storage pool tank is degraded. Your data has less protection until it is fixed. Open Storage and check the disks.",
    )
    title, msg = pool_alerts._text(item, "de")
    assert title == "Speicherpool tank ist beeinträchtigt" and "Speicher" in msg


def test_pool_alerts_are_sent_in_the_households_language(german, tmp_path, monkeypatch):
    monkeypatch.setattr(pool_alerts, "_state_file", lambda: str(tmp_path / "pool.json"))
    items = [{"id": "pool:tank:degraded", "kind": "pool_degraded", "subject": "tank", "level": "critical"}]
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: items)
    monkeypatch.setitem(pool_alerts._cache, "ok", True)
    sent = []
    pool_alerts.check_and_alert(now=1000, send=lambda **k: sent.append(k))
    assert sent[0]["title"] == "ZettNAS: Speicherpool tank ist beeinträchtigt"
    items.clear()
    pool_alerts.check_and_alert(now=2000, send=lambda **k: sent.append(k))
    assert sent[-1]["title"] == "ZettNAS: behoben — Speicherpool tank ist beeinträchtigt"
    assert sent[-1]["message"] == "Dieses Speicherproblem ist behoben."


def test_the_weekly_report_in_german(german, monkeypatch):
    monkeypatch.setattr(pool_alerts, "current", lambda max_age=0, now=None: [])
    monkeypatch.setattr(
        "backend.hardware.pal_storage.get_storage_platform", lambda: (_ for _ in ()).throw(RuntimeError("none"))
    )
    monkeypatch.setattr("backend.services.backup_watch.overdue_backups", lambda now: [{"name": "Fotos"}])
    title, body = pool_alerts.weekly_report(now=1000)
    assert title == "ZettNAS-Wochenbericht"
    assert "überfällig: Fotos" in body


def test_security_alert_titles_follow_the_language(monkeypatch):
    sent = []
    monkeypatch.setattr(notifications, "send_notification", lambda *a, **k: sent.append((a, k)))

    class Now:
        def __init__(self, target, name, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(security_alerts.threading, "Thread", Now)
    assert security_alerts.maybe_alert("auth.lockout", "blocked", "mia", "203.0.113.5")
    (args, kw) = sent[0]
    assert args[0] == "ZettNAS security: Sign-in locked after repeated failures"
    assert kw["text"]["title_key"] == "alert.security.title"
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "fr"})
    title, _ = notifications.in_household_language(args[0], args[1], kw["text"])
    assert title == "Sécurité ZettNAS : Connexion bloquée après plusieurs échecs"
