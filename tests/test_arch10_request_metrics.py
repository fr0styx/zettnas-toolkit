"""ARCH-10: request metrics by route template."""

from fastapi.testclient import TestClient

from backend.request_metrics import REQUEST_METRICS, RequestMetrics


def test_counts_latency_and_errors():
    m = RequestMetrics()
    for s in (0.004, 0.02, 0.2):
        m.observe("GET", "/api/storage/shares/{name}", 200, s)
    m.observe("GET", "/api/storage/shares/{name}", 500, 0.03)
    row = m.summary()[0]
    assert row["requests"] == 4 and row["server_errors"] == 1
    assert row["p50_ms_max"] == 25.0 and row["p95_ms_max"] == 250.0
    text = m.prometheus()
    assert 'zettnas_http_requests_total{method="GET",route="/api/storage/shares/{name}",status="5xx"} 1' in text
    assert 'le="+Inf"} 4' in text


def test_middleware_records_route_templates_not_raw_paths():
    from backend.main import app

    REQUEST_METRICS.reset()
    client = TestClient(app)
    client.get("/api/health")
    client.get("/api/health")
    client.get("/api/does-not-exist-123")
    routes = {(r["method"], r["route"]): r for r in REQUEST_METRICS.summary(top=50)}
    assert routes[("GET", "/api/health")]["requests"] == 2
    assert not any("does-not-exist-123" in r for (_, r) in routes)
