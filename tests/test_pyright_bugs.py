"""Bugs pyright found (OPS-24): calls to things that didn't exist."""

import time
from types import SimpleNamespace


def test_photo_on_sleeping_disk_is_queued_not_crashed(tmp_path):
    from backend.services.rag_engine import RagSearchEngine

    eng = RagSearchEngine(db_path=str(tmp_path / "r.db"))
    eng._ensure_schema()
    eng._record_deferred_subpath("/mnt/disk1/photos/a.jpg", "/dev/sdb")
    conn = eng._get_conn(readonly=True)
    try:
        rows = conn.execute("SELECT target_path, reason FROM rag_deferred_queue").fetchall()
    finally:
        conn.close()
    assert [tuple(r) for r in rows] == [("/mnt/disk1/photos/a.jpg", "disk_standby")]


def test_advisor_sees_guest_samba_shares(monkeypatch):
    from backend.services import samba_engine, security_advisor

    shares = [SimpleNamespace(name="public", guest_ok=True), SimpleNamespace(name="private", guest_ok=False)]
    monkeypatch.setattr(samba_engine, "get_samba_engine", lambda: SimpleNamespace(list_shares=lambda: shares))
    report = security_advisor.evaluate_security_posture(None)
    text = str(report)
    assert "public" in text and "private" not in text.split("public")[0][-200:]
