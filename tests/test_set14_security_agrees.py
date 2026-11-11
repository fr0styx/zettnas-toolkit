"""SET-14: the Overview and the security check agree. The Overview said "Everything is fine"
while the security check showed red rows."""

from backend.services import security_advisor, status_summary


def _posture(*severities, ids=None):
    ids = ids or [f"sec-issue-{n}" for n in range(len(severities))]
    return lambda _request=None: {"issues": [{"id": i, "severity": s} for i, s in zip(ids, severities, strict=True)]}


def test_serious_findings_are_one_row(monkeypatch):
    monkeypatch.setattr(security_advisor, "evaluate_security_posture", _posture("high", "medium", "high", "low"))
    assert status_summary._security() == [
        {"id": "security:check", "level": "warning", "kind": "security_look", "subject": "2", "open": "settings"}
    ]
    monkeypatch.setattr(security_advisor, "evaluate_security_posture", _posture("critical", "high"))
    assert status_summary._security()[0]["level"] == "critical"
    monkeypatch.setattr(security_advisor, "evaluate_security_posture", _posture("medium", "low"))
    assert status_summary._security() == []


def test_the_first_time_password_is_not_counted_twice(monkeypatch):
    monkeypatch.setattr(
        security_advisor,
        "evaluate_security_posture",
        _posture("critical", ids=["sec-issue-default-password"]),
    )
    assert status_summary._security() == []
    assert status_summary._security in status_summary.CHECKS
