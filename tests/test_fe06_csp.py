"""FE-06: report-only Content-Security-Policy and its report endpoint."""

from backend import csp


def test_policy_is_strict_where_it_can_be():
    p = csp.policy()
    assert "object-src 'none'" in p and "frame-ancestors 'self'" in p and "base-uri 'self'" in p
    assert "script-src 'self'" in p and "'unsafe-inline'" not in p.split("script-src")[1].split(";")[0]
    assert "report-uri /api/csp-report" in p


def test_html_pages_get_the_report_only_header(client):
    res = client.get("/")
    if res.headers.get("content-type", "").startswith("text/html"):
        assert "Content-Security-Policy-Report-Only" in res.headers


def test_reports_are_accepted_without_a_session_and_deduplicated(client):
    report = {
        "csp-report": {
            "violated-directive": "script-src-attr",
            "blocked-uri": "inline",
            "source-file": "x.js",
            "line-number": 7,
        }
    }
    assert client.post("/api/csp-report", json=report).status_code == 204
    assert csp.record_report(report) is False  # same violation within the hour is not logged again
    assert client.post("/api/csp-report", content=b"x" * 20000).status_code in (204, 413)
