"""NREL-8: a pool read that fails never announces problems as fixed."""

from backend.services import pool_alerts as pa

ITEM = {"id": "pool:tank:degraded", "level": "critical", "kind": "pool_degraded", "subject": "tank"}


def test_a_failed_read_keeps_problems_and_warns_once(tmp_path, monkeypatch):
    monkeypatch.setattr(pa, "_state_file", lambda: str(tmp_path / "pool_alerts.json"))
    monkeypatch.setattr(pa, "_cache", {"at": 0.0, "items": [], "ok": True, "failures": 0})
    monkeypatch.setattr(pa, "_text", lambda item: ("Pool tank is degraded", "Pool tank is degraded."))
    sent = []

    def send(**kw):
        sent.append(kw["title"])

    monkeypatch.setattr(pa, "_read", lambda: ({}, {}))
    monkeypatch.setattr(pa, "problems", lambda pools, scrubs: [dict(ITEM)])
    pa.check_and_alert(now=1000.0, send=send)
    assert sent == ["ZettNAS: Pool tank is degraded"]

    def broken():
        raise OSError("emhttp ini not readable")

    monkeypatch.setattr(pa, "_read", broken)
    for k in range(1, 5):
        out = pa.check_and_alert(now=1000.0 + k, send=send)
        assert out["fixed"] == []
    assert [t for t in sent if "fixed" in t] == []
    assert sent.count("ZettNAS can't read the storage health") == 1
    assert pa.current(max_age=0, now=2000.0) == [ITEM]  # still known

    monkeypatch.setattr(pa, "_read", lambda: ({}, {}))
    monkeypatch.setattr(pa, "problems", lambda pools, scrubs: [])
    out = pa.check_and_alert(now=3000.0, send=send)
    assert out["fixed"] == ["pool:tank:degraded"]  # only a good read says fixed
