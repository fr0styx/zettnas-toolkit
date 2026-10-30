"""NUX-3: backup, fan, processor-heat and UPS alerts in the household's language."""

from backend.services import notifications


def test_english_stays_as_written_and_other_languages_use_the_keys(monkeypatch):
    text = {
        "title_key": "alert.backup_failed.title",
        "msg_key": "alert.backup_failed.msg",
        "params": {"name": "Photos", "error": "disk full"},
    }
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "en"})
    assert notifications.in_household_language("Backup failed: Photos", "orig", text) == (
        "Backup failed: Photos",
        "orig",
    )
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "de"})
    title, msg = notifications.in_household_language("Backup failed: Photos", "orig", text)
    assert title == "Sicherung fehlgeschlagen: Photos" and msg.endswith("disk full")
    assert notifications.in_household_language("t", "m", {"params": {}}) == ("t", "m")


def test_send_notification_writes_it_in_that_language(monkeypatch):
    seen = {}
    cfg = {**notifications.DEFAULT_NOTIFICATION_CONFIG, "language": "fr", "enabled": False, "push_enabled": False}
    monkeypatch.setattr(notifications, "load_notification_config", lambda: cfg)
    real = notifications.in_household_language

    def spy(title, message, text):
        seen["out"] = real(title, message, text)
        return seen["out"]

    monkeypatch.setattr(notifications, "in_household_language", spy)
    notifications.send_notification(
        {
            "title": "x",
            "message": "y",
            "level": "info",
            "type": "backup",
            "text": {"title_key": "alert.backup_ok.title", "params": {"name": "Docs"}},
        }
    )
    assert seen["out"][0] == "Sauvegarde terminée : Docs"
    notifications.send_notification(
        "a",
        "b",
        text={"title_key": "alert.cpu_hot.warn.title", "msg_key": "alert.cpu_hot.warn.msg", "params": {"temp": 81}},
    )
    assert seen["out"] == ("Le processeur chauffe", "Il est à 81°C.")


def test_the_alert_sites_pass_their_keys():
    import inspect

    from backend.services import backup_engine, stats_collector, ups_watchdog

    assert 'alert_text("backup_failed"' in inspect.getsource(backup_engine)
    failed = backup_engine._backup_notice({"name": "Docs"}, "j1", "p", error="disk full")
    assert failed["text"] == {
        "title_key": "alert.backup_failed.title",
        "msg_key": "alert.backup_failed.msg",
        "params": {"name": "Docs", "error": "disk full"},
    }
    assert backup_engine._backup_notice({}, "j2", "p", snapshot="s1")["message"].endswith("Snapshot: s1")
    assert stats_collector._text("fan_stall", fans="pwm1") == {
        "title_key": "alert.fan_stall.title",
        "msg_key": "alert.fan_stall.msg",
        "params": {"fans": "pwm1"},
    }
    assert 'alert_text("ups_manual")' in inspect.getsource(ups_watchdog)


def test_every_key_is_in_every_language():
    from backend import i18n

    keys = [
        "alert.backup_ok.title",
        "alert.backup_ok.msg",
        "alert.backup_failed.title",
        "alert.backup_failed.msg",
        "alert.fan_stall.title",
        "alert.fan_stall.msg",
        "alert.cpu_hot.crit.title",
        "alert.cpu_hot.crit.msg",
        "alert.cpu_hot.warn.title",
        "alert.cpu_hot.warn.msg",
        "alert.ups_manual.title",
        "alert.ups_manual.msg",
    ]
    for lang in i18n.LANGS:
        assert all(k in i18n.strings(lang) for k in keys), lang
