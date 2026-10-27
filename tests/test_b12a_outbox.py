"""B12a (REL-22): an alert whose channels all failed waits in an outbox and is tried again; the
cooldown counts from the last alert that got through; smb.conf is written atomically."""

import os
import time

import pytest

from backend.services import notifications as nt


@pytest.fixture
def channels(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "NOTIFICATIONS_FILE", str(tmp_path / "notifications.json"))
    monkeypatch.setattr(nt, "OUTBOX_FILE", str(tmp_path / "outbox.json"))
    monkeypatch.setattr(nt, "ROUTES_FILE", str(tmp_path / "routes.json"))
    nt._alert_history.clear()
    nt.save_notification_config(
        {"enabled": True, "cooldown_seconds": 600, "unraid_notify": True, "push_enabled": False}
    )
    state = {"up": False, "sent": 0}

    def unraid(script, title, message, level):
        if state["up"]:
            state["sent"] += 1
        return state["up"]

    monkeypatch.setattr(nt, "_find_unraid_notify", lambda: "/mock/notify")
    monkeypatch.setattr(nt, "_dispatch_unraid", unraid)
    return state


def test_a_failed_alert_waits_and_is_sent_when_the_channel_is_back(channels):
    r = nt.send_notification("Drive failing", "sdb", level="critical", event_type="smart", dedup_key="sdb")
    assert r["dispatched"] is False and r["reason"] == "queued for retry"
    # the same alert again is not stacked up, and the failure did not start a cooldown
    assert nt.send_notification("Drive failing", "sdb", level="critical", dedup_key="sdb")["reason"] == "queued"
    now = time.time()
    assert nt.retry_outbox(now)["sent"] == []  # not due yet
    channels["up"] = True
    assert nt.retry_outbox(now + 61)["sent"] == ["Drive failing"]
    assert channels["sent"] == 1 and nt._outbox() == []
    # now that it got through, the cooldown applies
    assert nt.send_notification("Drive failing", "sdb", level="critical", dedup_key="sdb")["reason"] == "cooldown"


def test_retries_wait_longer_each_time_and_then_give_up(channels, monkeypatch):
    events = []
    monkeypatch.setattr("backend.state.add_event", lambda *a, **k: events.append(a[1]))
    nt.send_notification("UPS on battery", "x", level="warning", event_type="ups")
    now = nt._outbox()[0]["next_try"]
    waits, dropped = [], []
    while nt._outbox():
        out = nt.retry_outbox(now)
        dropped += out["dropped"]
        if nt._outbox():
            nxt = nt._outbox()[0]["next_try"]
            waits.append(round(nxt - now))
            now = nxt
    assert waits == list(nt.RETRY_DELAYS[1:])  # 5 min, 15 min, then hourly
    assert dropped == ["UPS on battery"] and "An alert could not be sent" in events


def test_the_scheduler_retries_and_survives_a_failure(monkeypatch):
    from backend.services import scheduler

    calls = []
    monkeypatch.setattr(nt, "retry_outbox", lambda now: calls.append(now))
    scheduler._run_alert_retries(5.0)
    assert calls == [5.0]
    monkeypatch.setattr(nt, "retry_outbox", lambda now: 1 / 0)
    scheduler._run_alert_retries(5.0)  # logged


def test_smb_conf_is_written_in_one_step(tmp_path, monkeypatch):
    from backend.fsutil import atomic_write_text
    from backend.services import samba_engine
    from backend.services.samba_engine import SambaShareConfig

    target = tmp_path / "smb.conf"
    atomic_write_text(str(target), "[global]\n")
    assert target.read_text() == "[global]\n" and oct(target.stat().st_mode & 0o777) == "0o644"
    monkeypatch.setattr(samba_engine, "SAMBA_CONF_FILE", str(target))
    monkeypatch.setattr(samba_engine, "validate_share", lambda share: None)
    engine = samba_engine.SambaEngine.__new__(samba_engine.SambaEngine)
    engine._shares = {"a": SambaShareConfig(name="a", path=str(tmp_path))}
    written = []
    real = samba_engine.atomic_write_text
    monkeypatch.setattr(samba_engine, "atomic_write_text", lambda p, t: written.append(p) or real(p, t))
    engine.generate_and_save_conf()
    assert written == [str(target)] and "[a]" in target.read_text()
    assert not [n for n in os.listdir(tmp_path) if n.startswith(".tmp-")]
