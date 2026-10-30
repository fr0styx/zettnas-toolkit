"""NUX-3: alerts are written in the household's language, and the activity log keeps the keys to
show them in the reader's."""

import pytest

from backend import i18n
from backend.services import drive_alerts, notifications


def test_placeholders_plurals_and_fallbacks():
    assert i18n.fill("{n, plural, one {# drive} other {# drives}}", {"n": 1}) == "1 drive"
    assert i18n.fill("{n, plural, one {# drive} other {# drives}} left", {"n": 3}) == "3 drives left"
    assert i18n.fill("{n, plural, =0 {none} one {# file} other {# files}}", {"n": 0}) == "none"
    assert i18n.fill("{n, plural, one {# disque} other {# disques}}", {"n": 0}, "fr") == "0 disque"
    assert i18n.fill("{n, plural, one {# 块} other {# 块硬盘}}", {"n": 1}, "zh") == "1 块硬盘"
    assert i18n.fill("{a} and {b}", {"a": 1}) == "1 and {b}"
    assert i18n.t("alert.drive_verdict.title", "", {"dev": "sdb", "label": "x"}, "de") == "Laufwerk sdb: x"
    assert i18n.t("no.such.key", "Default {x}", {"x": 2}, "de") == "Default 2"
    assert i18n.t("no.such.key") == "no.such.key"
    assert i18n.strings("klingon") == {}
    label = i18n.ref("dh.label.soon_replace", "Replace soon")
    assert (
        i18n.text("alert.drive_verdict.title", "", {"dev": "sdb", "label": label}, "de")
        == "Laufwerk sdb: Bald austauschen"
    )


def test_the_language_setting(monkeypatch):
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "fr"})
    assert notifications.alert_language() == "fr"
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "xx"})
    assert notifications.alert_language() == "en"
    assert notifications.DEFAULT_NOTIFICATION_CONFIG["language"] == "en"


@pytest.fixture
def german(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_alerts, "_state_file", lambda: str(tmp_path / "alerts.json"))
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "de"})
    events = []
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append((a, k)))
    return events


def test_a_verdict_alert_reads_in_the_households_language(german):
    sent = []
    result = {
        "verdict": "soon",
        "label": "Replace soon",
        "label_key": "soon_replace",
        "summary": "Parts of the disk could not be read",
        "summary_key": "unreadable_sectors",
        "summary_params": {},
    }
    assert drive_alerts.on_verdict("sdb", result, key="serial:X", now=1000, send=lambda **k: sent.append(k)) == "alert"
    assert sent[0]["title"] == "Laufwerk sdb: Bald austauschen"
    assert sent[0]["message"].endswith("Was zu tun ist, steht in Laufwerkszustand.")
    (args, kw) = german[0]
    assert args[1] == "Drive sdb: Replace soon"  # the log file stays English
    assert kw["details"]["title_key"] == "alert.drive_verdict.title"
    assert kw["details"]["params"]["label"]["key"] == "dh.label.soon_replace"


def test_better_and_plain_messages(german):
    sent = []
    drive_alerts.on_verdict(
        "sdc", {"verdict": "soon", "label": "Replace soon"}, key="k2", now=1000, send=lambda **k: sent.append(k)
    )
    assert sent[0]["message"] == "Was zu tun ist, steht in Laufwerkszustand."
    assert (
        drive_alerts.on_verdict("sdc", {"verdict": "ok", "label": "Healthy", "label_key": "ok"}, key="k2", now=2000)
        == "better"
    )
    assert german[-1][0][2] == "The drive looks better than before."


def test_temperature_alerts_read_in_the_households_language(monkeypatch):
    monkeypatch.setattr(notifications, "load_notification_config", lambda: {"language": "de"})
    drive_alerts._hot.clear()
    sent = []
    drive_alerts.check_temperatures([{"dev": "sdq", "temp": 61}], 50, lambda **k: sent.append(k))
    assert sent[0]["title"] == "Laufwerk sdq ist zu heiß (61°C)"
    assert "Lüfter" in sent[0]["message"]
    drive_alerts._hot.clear()


def test_the_settings_api_takes_the_language(client, auth_headers):
    cfg = client.get("/api/notifications/config", headers=auth_headers).json()
    cfg["language"] = "es"
    r = client.post("/api/notifications/config", headers=auth_headers, json=cfg)
    assert r.status_code == 200, r.text
    assert client.get("/api/notifications/config", headers=auth_headers).json()["language"] == "es"
    cfg["language"] = "xx"
    assert client.post("/api/notifications/config", headers=auth_headers, json=cfg).status_code == 422
