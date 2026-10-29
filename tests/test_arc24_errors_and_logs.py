"""ARC-24: a client\x27s correlation ID is taken only when it is a short plain token, and threads a
request starts log with that request\x27s ID."""

import threading

from backend.logging_config import correlation_id_ctx, correlation_id_from, in_this_request


def test_only_plain_short_ids_are_taken():
    assert correlation_id_from("job-42.retry_1") == "job-42.retry_1"
    for bad in ("two words", "line\\nbreak", "x" * 65, "<script>", "", None):
        made = correlation_id_from(bad)
        assert made != bad and len(made) == 16


def test_the_header_is_checked(client):
    ok = client.get("/api/health", headers={"X-Correlation-ID": "abc-123"})
    assert ok.headers["X-Correlation-ID"] == "abc-123"
    bad = client.get("/api/health", headers={"X-Correlation-ID": "forged\\tlog line"})
    assert bad.headers["X-Correlation-ID"] != "forged\\tlog line"


def test_a_started_thread_keeps_the_request_id():
    seen = []
    token = correlation_id_ctx.set("req-7")
    try:
        t = threading.Thread(target=in_this_request(lambda: seen.append(correlation_id_ctx.get())))
        t.start()
        t.join()
    finally:
        correlation_id_ctx.reset(token)
    assert seen == ["req-7"]
